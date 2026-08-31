#!/usr/bin/env python3
"""Build the site and publish it to the bunny.net storage zone behind anomalica.is.

Nothing else deploys this site: there is no CI and no timer, so a commit in
`content` (mounted into the build, not copied) reaches a reader only when this
runs. It lived in /tmp during the June launch, /tmp was cleared, and the live
site silently fell eight weeks behind. Hence a committed script.

Four traps it exists to close, each of which has bitten before:

- A running `hugo server` rewrites ./public with DEV output - unfingerprinted
  asset paths that 404 in production, which once shipped a half-broken site.
  The build here goes to its own temporary directory and never touches public/.
- Bunny storage keeps whatever was uploaded before. A page the build no longer
  produces goes on being served until it is explicitly deleted.
- The pull zone serves its cache until purged, so an upload alone changes
  nothing a reader sees.
- A dead internal link is invisible in a build log. Every internal href is
  resolved against the built output before anything is uploaded.

Usage:
    scripts/deploy.py              # build, verify, upload changed files, purge
    scripts/deploy.py --dry-run    # build and verify only; reports the diff
    scripts/deploy.py --keep-build # leave the build directory for inspection
"""

from __future__ import annotations

import argparse
import concurrent.futures
import tarfile
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ZONE = "anomalica-site"
STORAGE_API = "https://storage.bunnycdn.com"
BUNNY_API = "https://api.bunny.net"
LIVE_ORIGIN = "https://anomalica.is"

SAFE = Path.home() / "repos/secrets/store/anomalica.yaml"
SOPS = Path.home() / ".nix-profile/bin/sops"
AGE_KEY = Path.home() / ".config/sops/age/keys.txt"

UPLOAD_WORKERS = 8

CONTENT_REPO = REPO.parent / "content"
REDIRECTS = REPO / "data/redirects.yaml"
CONTENT_ROOTS = (REPO / "content/english", CONTENT_REPO / "pages")
# One level of nesting, so a role description keeps its brackets: [[redacted]](/x).
MARKDOWN_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\((/[^)\s]*)\)")
# Mirrors layouts/partials/is-role-description.html: a stand-in for an unknown
# person is never meant to resolve, so it is not a missing page.
ROLE_DESCRIPTION = re.compile(r"(?i)^\[?\s*speaker\s+\d+\s*\]?$")
DEFAULT_LANGUAGE = "en"


class DeployError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


# --- credentials -------------------------------------------------------------


def secret(key: str) -> str:
    """Read one value from the Safe.

    sops is not on PATH (nix profile), and it segfaults under the inherited
    LD_PRELOAD that the desktop session sets, so both are corrected here.
    """
    env = dict(os.environ)
    env["PATH"] = f"{Path.home()}/.nix-profile/bin:" + env.get("PATH", "")
    env.setdefault("SOPS_AGE_KEY_FILE", str(AGE_KEY))
    env.pop("LD_PRELOAD", None)
    result = subprocess.run(
        [str(SOPS), "-d", "--extract", f'["{key}"]', str(SAFE)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise DeployError(
            f"could not read {key} from the Safe: {result.stderr.strip()}"
        )
    return result.stdout.strip()


# --- the content repo -------------------------------------------------------


def content_state() -> tuple[str, str, list[str]]:
    """Branch, commit and uncommitted files of the mounted content repository."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(CONTENT_REPO), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "--short", "HEAD")
    dirty = [line[2:].strip() for line in git("status", "--porcelain").splitlines()]
    return branch, head, dirty


def snapshot_content(destination: Path) -> Path:
    """Export the content repo at HEAD, and build against that instead of the tree.

    The build MOUNTS this repository, so without this it publishes whatever is on
    disk at the moment hugo runs - a page the assembler is halfway through
    writing, or whichever branch happens to be checked out. Neither shows up in a
    build log. Exporting HEAD means a deploy always publishes a committed state
    and the assembler can keep working while it runs.
    """
    branch, head, dirty = content_state()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / "content.tar"
    with archive.open("wb") as handle:
        subprocess.run(
            ["git", "-C", str(CONTENT_REPO), "archive", "HEAD"],
            stdout=handle,
            check=True,
        )
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")
    archive.unlink()
    uncommitted = f" ({len(dirty)} uncommitted, not published)" if dirty else ""
    log(f"Content repo {branch} at {head}{uncommitted}")
    return destination


# --- build -------------------------------------------------------------------


def module_override(content_source: Path, path: Path) -> Path:
    """A second config that re-points the content mounts at the snapshot.

    Generated from the project's own mounts rather than restated, so it keeps
    working when hugo.toml changes.
    """
    import tomllib

    config = tomllib.loads((REPO / "hugo.toml").read_text())
    lines = ["[module]"]
    for mount in config.get("module", {}).get("mounts", []):
        source = mount["source"]
        if source.startswith("../content/"):
            source = str(content_source / source[len("../content/") :])
        lines.append("[[module.mounts]]")
        for key, value in mount.items():
            rendered = f'"{source}"' if key == "source" else json.dumps(value)
            lines.append(f"{key} = {rendered}")
    path.write_text("\n".join(lines) + "\n")
    return path


def build(destination: Path, content_source: Path) -> None:
    log(f"Building into {destination}")
    subprocess.run(["npm", "run", "vendor", "--silent"], cwd=REPO, check=True)
    # The committed compiled.css is the readable build the dev server watches.
    # Minifying writes over it in place, so it is put back afterwards: a deploy
    # must not leave the working tree dirty.
    stylesheet = REPO / "assets/css/compiled.css"
    committed = stylesheet.read_bytes() if stylesheet.exists() else None
    try:
        subprocess.run(
            [
                "npx",
                "@tailwindcss/cli",
                "-i",
                "assets/css/main.css",
                "-o",
                "assets/css/compiled.css",
                "--minify",
            ],
            cwd=REPO,
            check=True,
            capture_output=True,
        )
        # -e production is load-bearing: without it hugo.IsProduction is false in
        # this environment and templates render their development branch.
        override = module_override(content_source, destination.parent / "mounts.toml")
        subprocess.run(
            [
                "hugo",
                "--gc",
                "--minify",
                "-e",
                "production",
                "-d",
                str(destination),
                "--config",
                f"hugo.toml,{override}",
            ],
            cwd=REPO,
            check=True,
        )
    finally:
        if committed is not None:
            stylesheet.write_bytes(committed)


def apply_redirects(build_dir: Path) -> None:
    """Write a redirect for every retired URL that no longer has a page.

    Hugo's own aliases live in the destination page's front matter, which the
    assembler regenerates on every write - so they can only carry a slug that
    entity itself once had. A page merged INTO a different entity leaves a URL
    no front matter will ever claim, and hand-adding one there has been undone
    by a rebuild before. These live in this repo instead.

    Skipped while a real page still occupies the path: an entry can be added
    before the page is removed, and starts working by itself when it goes.
    """
    if not REDIRECTS.is_file():
        return
    entries = (yaml.safe_load(REDIRECTS.read_text()) or {}).get("redirects") or []
    written = skipped = 0
    for entry in entries:
        source = entry["from"].strip("/")
        target = entry["to"]
        page = build_dir / source / "index.html"
        if page.exists():
            log(f"  redirect skipped, a page still serves /{source}/")
            skipped += 1
            continue
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{LIVE_ORIGIN}{target}</title>"
            f'<link rel="canonical" href="{LIVE_ORIGIN}{target}">'
            '<meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={target}">'
            f'</head><body><a href="{target}">{LIVE_ORIGIN}{target}</a></body></html>'
        )
        written += 1
    if written or skipped:
        log(f"  {written} retired URL(s) redirected, {skipped} still served by a page")


def verify_assets_fingerprinted(build_dir: Path) -> None:
    """Assert the build carries production asset paths, not a dev server's."""
    home = build_dir / "en/index.html"
    if not home.exists():
        raise DeployError("build produced no en/index.html")
    html = home.read_text(errors="replace")
    references = re.findall(r'["\'=](/js/[a-z0-9.-]+\.js)', html)
    if not references:
        raise DeployError("no /js/ asset reference found in the homepage")
    unfingerprinted = [
        r for r in references if not re.search(r"\.[0-9a-f]{32,}\.js$", r)
    ]
    if unfingerprinted:
        raise DeployError(
            "dev-mode asset paths in the build - a dev server clobbered it: "
            + ", ".join(unfingerprinted)
        )
    log(f"  assets fingerprinted ({len(references)} references)")


def verify_no_dead_links(build_dir: Path) -> None:
    """Resolve every internal href against the built output."""
    dead: dict[str, set[str]] = {}
    pages = list(build_dir.rglob("*.html"))
    for page in pages:
        html = page.read_text(errors="replace")
        # Minified output drops the quotes, so both forms have to be matched.
        hrefs = re.findall(r'href=(?:"([^"]+)"|\'([^\']+)\'|([^\s>]+))', html)
        for quoted, single, bare in hrefs:
            href = quoted or single or bare
            if href.startswith(LIVE_ORIGIN):
                href = href[len(LIVE_ORIGIN) :]
            if not href.startswith("/") or href.startswith("//"):
                continue
            path = href.split("#")[0].split("?")[0]
            if not path or not resolves(build_dir, path):
                dead.setdefault(path or href, set()).add(
                    str(page.relative_to(build_dir))
                )
    if dead:
        for target, sources in sorted(dead.items())[:20]:
            log(f"  DEAD {target}  <- {sorted(sources)[0]}")
        raise DeployError(
            f"{len(dead)} dead internal link target(s); refusing to deploy"
        )
    log(f"  no dead internal links across {len(pages)} pages")


def report_alias_changes(build_dir: Path, persist: bool) -> None:
    """Name any redirect that has stopped being built.

    Aliases live in a page's front matter, so a rebuild of that page silently
    drops them - and because the build no longer emits the redirect, the deploy
    dutifully deletes it and a URL that worked an hour ago starts 404ing. That
    has happened once already, to /people/david-grusch/ and /organisations/nasa/.
    Nothing else reports it: the alias is not a page, so no page count changes.
    """
    current = sorted(
        "/" + str(page.parent.relative_to(build_dir)) + "/"
        for page in build_dir.rglob("index.html")
        if "http-equiv=refresh" in page.read_text(errors="replace")[:600]
    )
    previous = read_state().get("aliases", [])
    dropped = [alias for alias in previous if alias not in current]
    if dropped:
        log(f"  WARNING: {len(dropped)} redirect(s) no longer built - these will 404:")
        for alias in dropped:
            log(f"    {alias}")
    log(f"  {len(current)} redirect(s) in the build")
    if persist:
        write_state("aliases", current)


def resolves(build_dir: Path, path: str) -> bool:
    target = build_dir / path.lstrip("/")
    if target.is_file():
        return True
    return (target / "index.html").is_file()


LINK_STATE = REPO / ".deploy-link-state.json"


def read_state() -> dict:
    return json.loads(LINK_STATE.read_text()) if LINK_STATE.exists() else {}


def write_state(key: str, value) -> None:
    """Merge one key into the state file.

    Each reporter keeps its own baseline in here, so a whole-file write from one
    of them silently wipes another's - which is how the alias guard came to miss
    the first regression it was written for.
    """
    state = read_state()
    state[key] = value
    LINK_STATE.write_text(json.dumps(state, indent=1, sort_keys=True))


def report_unresolved_links(
    build_dir: Path,
    content_source: Path | None = None,
    persist: bool = False,
    limit: int = 15,
) -> int:
    """Count internal links the templates had to strip for want of a page.

    These never reach the HTML - the markdown link hook renders them as plain
    text when the target does not exist - so the dead-link assertion above
    cannot see them. This is the number that measures assembly progress: it
    should fall as entity pages land, and a rise means the assembler is
    emitting links to pages nobody is building.
    """
    roots = (
        (REPO / "content/english", content_source / "pages")
        if content_source
        else CONTENT_ROOTS
    )
    inbound: dict[str, set[str]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for source in root.rglob("*.md"):
            text = source.read_text(errors="replace")
            for label, target in MARKDOWN_LINK.findall(text):
                if target.startswith("//"):
                    continue
                if label.startswith("[") and label.endswith("]"):
                    continue
                if ROLE_DESCRIPTION.match(label):
                    continue
                path = target.split("#")[0].split("?")[0]
                if not resolves_in_language(build_dir, path):
                    inbound.setdefault(path, set()).add(source.name)

    counts = {target: len(sources) for target, sources in inbound.items()}
    total = sum(counts.values())
    log(f"  {total} stripped link(s) to {len(counts)} missing page(s)")
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    for target, count in ranked[:limit]:
        log(f"    {count:3d}  {target}")
    if len(ranked) > limit:
        log(f"    ... {len(ranked) - limit} more")

    # The total barely moves between tranches: pages that land clear their own
    # inbound links while bringing new outbound ones to pages nobody has built
    # yet. The split is the signal - a flat total is churn, a rising ADDED with
    # nothing cleared is the assembler linking into empty space.
    previous = read_state().get("targets", {})
    if previous:
        cleared = {k: v for k, v in previous.items() if k not in counts}
        added = {k: v for k, v in counts.items() if k not in previous}
        log(
            f"  since the last deploy: cleared {sum(cleared.values())} link(s) "
            f"to {len(cleared)} page(s), added {sum(added.values())} to {len(added)}"
        )
        for target, count in sorted(added.items(), key=lambda kv: -kv[1])[:5]:
            log(f"    +{count:3d}  {target}")
    if persist:
        write_state("targets", counts)
    return total


def resolves_in_language(build_dir: Path, path: str) -> bool:
    """Content links are language-agnostic (/people/x); output is not (/en/...)."""
    return resolves(build_dir, path) or resolves(
        build_dir, f"/{DEFAULT_LANGUAGE}{path}"
    )


# --- remote state ------------------------------------------------------------


def request(
    method: str, url: str, key: str, body: bytes | None = None, timeout: int = 120
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("AccessKey", key)
    if body is not None:
        req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def list_remote_directory(key: str, prefix: str) -> tuple[dict[str, str], list[str]]:
    status, payload = request("GET", f"{STORAGE_API}/{ZONE}/{prefix}", key)
    if status != 200:
        raise DeployError(f"listing {prefix or '/'} failed: {status}")
    files: dict[str, str] = {}
    directories: list[str] = []
    for entry in json.loads(payload or b"[]"):
        name = entry["ObjectName"]
        if entry.get("IsDirectory"):
            directories.append(f"{prefix}{name}/")
        else:
            files[f"{prefix}{name}"] = (entry.get("Checksum") or "").lower()
    return files, directories


def remote_files(key: str) -> dict[str, str]:
    """Map every stored path to its SHA256.

    One request per directory, and the zone has one per page, so this is walked
    a level at a time in parallel - serially it dominated the whole deploy.
    """
    found: dict[str, str] = {}
    level = [""]
    with concurrent.futures.ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        while level:
            next_level: list[str] = []
            for files, directories in pool.map(
                lambda prefix: list_remote_directory(key, prefix), level
            ):
                found.update(files)
                next_level.extend(directories)
            level = next_level
    return found


def local_files(build_dir: Path) -> dict[str, tuple[Path, str]]:
    files: dict[str, tuple[Path, str]] = {}
    for path in build_dir.rglob("*"):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files[str(path.relative_to(build_dir))] = (path, digest)
    return files


# --- publish -----------------------------------------------------------------


def upload(key: str, relative: str, path: Path) -> None:
    url = f"{STORAGE_API}/{ZONE}/{urllib.parse.quote(relative)}"
    status, payload = request("PUT", url, key, body=path.read_bytes())
    if status not in (200, 201):
        raise DeployError(f"upload {relative}: {status} {payload[:200]!r}")


def delete(key: str, relative: str) -> None:
    url = f"{STORAGE_API}/{ZONE}/{urllib.parse.quote(relative)}"
    status, payload = request("DELETE", url, key)
    if status not in (200, 404):
        raise DeployError(f"delete {relative}: {status} {payload[:200]!r}")


def in_parallel(action, items) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        for future in concurrent.futures.as_completed(
            [pool.submit(action, item) for item in items]
        ):
            future.result()


def purge(api_key: str) -> None:
    """Purge the whole pull zone, so every hostname it serves drops its cache."""
    status, payload = request("GET", f"{BUNNY_API}/pullzone", api_key)
    if status != 200:
        raise DeployError(f"could not list pull zones: {status}")
    zone_id = next(
        (z["Id"] for z in json.loads(payload) if z.get("Name") == ZONE), None
    )
    if zone_id is None:
        raise DeployError(f"no pull zone named {ZONE}")
    status, payload = request(
        "POST", f"{BUNNY_API}/pullzone/{zone_id}/purgeCache", api_key, body=b""
    )
    if status not in (200, 204):
        raise DeployError(f"purge failed: {status} {payload[:200]!r}")
    log(f"  purged pull zone {zone_id}")


def verify_live(
    build_dir: Path, paths: list[str], attempts: int = 6, wait: int = 5
) -> None:
    """Assert the live page IS the page just built, not merely that it answers.

    A status code cannot tell "deployed and propagated" from "deployed, not yet
    visible": a purge takes a few seconds to reach every edge, and a check that
    runs immediately reads the old page and calls it a success - or, if it looks
    for new content, calls a working deploy a failure. Comparing the body hash
    against the built file answers exactly, and retrying covers the window.
    """
    for path in paths:
        url = f"{LIVE_ORIGIN}{path}"
        local = build_dir / path.strip("/") / "index.html"
        expected = (
            hashlib.sha256(local.read_bytes()).hexdigest() if local.is_file() else None
        )
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    status = response.status
                    served = hashlib.sha256(response.read()).hexdigest()
            except urllib.error.HTTPError as exc:
                raise DeployError(f"{url} served {exc.code}") from exc
            if status != 200:
                raise DeployError(f"{url} served {status}")
            if expected is None or served == expected:
                log(f"  {status}  {url}")
                break
            if attempt == attempts:
                raise DeployError(
                    f"{url} answers but does not match the build after "
                    f"{attempts * wait}s - the purge did not take"
                )
            time.sleep(wait)


# --- entry point -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="build and verify only")
    parser.add_argument(
        "--keep-build", action="store_true", help="do not remove the build directory"
    )
    args = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="anomalica-site-"))
    build_dir = workspace / "site"
    try:
        content_source = snapshot_content(workspace / "content")
        build(build_dir, content_source)
        apply_redirects(build_dir)
        log("Verifying the build")
        verify_assets_fingerprinted(build_dir)
        verify_no_dead_links(build_dir)
        report_unresolved_links(
            build_dir, content_source=content_source, persist=not args.dry_run
        )
        report_alias_changes(build_dir, persist=not args.dry_run)

        storage_key = secret("BUNNY_SITE_STORAGE_PASSWORD")
        local = local_files(build_dir)
        remote = remote_files(storage_key)

        changed = [
            name for name, (_, digest) in local.items() if remote.get(name) != digest
        ]
        orphaned = sorted(set(remote) - set(local))
        log(
            f"{len(local)} files built; {len(changed)} new or changed, "
            f"{len(orphaned)} to remove"
        )

        if args.dry_run:
            for name in sorted(changed)[:40]:
                log(f"  would upload {name}")
            for name in orphaned[:40]:
                log(f"  would delete {name}")
            return 0

        if changed:
            in_parallel(lambda name: upload(storage_key, name, local[name][0]), changed)
            log(f"  uploaded {len(changed)}")
        if orphaned:
            in_parallel(lambda name: delete(storage_key, name), orphaned)
            log(f"  deleted {len(orphaned)}")

        if changed or orphaned:
            purge(secret("BUNNY_API_KEY"))
            checks = ["/en/"] + [
                "/" + name.rsplit("/index.html", 1)[0] + "/"
                for name in sorted(changed)
                if name.endswith("/index.html")
            ][:3]
            log("Verifying live")
            verify_live(build_dir, checks)
        else:
            log("Nothing to publish; the zone already matches the build")
        return 0
    except (DeployError, subprocess.CalledProcessError) as exc:
        print(f"deploy failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.keep_build:
            log(f"build left at {build_dir}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
