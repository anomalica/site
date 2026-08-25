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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ZONE = "anomalica-site"
STORAGE_API = "https://storage.bunnycdn.com"
BUNNY_API = "https://api.bunny.net"
LIVE_ORIGIN = "https://anomalica.is"

SAFE = Path.home() / "repos/secrets/store/anomalica.yaml"
SOPS = Path.home() / ".nix-profile/bin/sops"
AGE_KEY = Path.home() / ".config/sops/age/keys.txt"

UPLOAD_WORKERS = 8

CONTENT_ROOTS = (REPO / "content/english", REPO.parent / "content/pages")
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


# --- build -------------------------------------------------------------------


def build(destination: Path) -> None:
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
        subprocess.run(
            ["hugo", "--gc", "--minify", "-e", "production", "-d", str(destination)],
            cwd=REPO,
            check=True,
        )
    finally:
        if committed is not None:
            stylesheet.write_bytes(committed)


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


def resolves(build_dir: Path, path: str) -> bool:
    target = build_dir / path.lstrip("/")
    if target.is_file():
        return True
    return (target / "index.html").is_file()


def report_unresolved_links(build_dir: Path, limit: int = 15) -> int:
    """Count internal links the templates had to strip for want of a page.

    These never reach the HTML - the markdown link hook renders them as plain
    text when the target does not exist - so the dead-link assertion above
    cannot see them. This is the number that measures assembly progress: it
    should fall as entity pages land, and a rise means the assembler is
    emitting links to pages nobody is building.
    """
    inbound: dict[str, set[str]] = {}
    for root in CONTENT_ROOTS:
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

    total = sum(len(sources) for sources in inbound.values())
    log(f"  {total} stripped link(s) to {len(inbound)} missing page(s)")
    ranked = sorted(inbound.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for target, sources in ranked[:limit]:
        log(f"    {len(sources):3d}  {target}")
    if len(ranked) > limit:
        log(f"    ... {len(ranked) - limit} more")
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


def remote_files(key: str, prefix: str = "") -> dict[str, str]:
    """Map every stored path to its SHA256, walking the zone depth-first."""
    url = f"{STORAGE_API}/{ZONE}/{prefix}"
    status, payload = request("GET", url, key)
    if status != 200:
        raise DeployError(f"listing {prefix or '/'} failed: {status}")
    found: dict[str, str] = {}
    for entry in json.loads(payload or b"[]"):
        name = entry["ObjectName"]
        if entry.get("IsDirectory"):
            found.update(remote_files(key, f"{prefix}{name}/"))
        else:
            found[f"{prefix}{name}"] = (entry.get("Checksum") or "").lower()
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


def verify_live(paths: list[str]) -> None:
    for path in paths:
        url = f"{LIVE_ORIGIN}{path}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                log(f"  {response.status}  {url}")
                if response.status != 200:
                    raise DeployError(f"{url} served {response.status}")
        except urllib.error.HTTPError as exc:
            raise DeployError(f"{url} served {exc.code}") from exc


# --- entry point -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="build and verify only")
    parser.add_argument(
        "--keep-build", action="store_true", help="do not remove the build directory"
    )
    args = parser.parse_args()

    build_dir = Path(tempfile.mkdtemp(prefix="anomalica-site-"))
    try:
        build(build_dir)
        log("Verifying the build")
        verify_assets_fingerprinted(build_dir)
        verify_no_dead_links(build_dir)
        report_unresolved_links(build_dir)

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
            verify_live(checks)
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
            shutil.rmtree(build_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
