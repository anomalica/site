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
import html
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

if __package__:
    from .deployment_freshness import (
        deployment_freshness_result,
        inherited_groups_from_manifest,
        reason_code_contract,
    )
else:
    from deployment_freshness import (
        deployment_freshness_result,
        inherited_groups_from_manifest,
        reason_code_contract,
    )

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
META_REPO = REPO.parent / "anomalica"
MOUNTED_META_INPUTS = (
    "reference/format-specs.yaml",
    "reference/architecture.yaml",
    "architecture/model-policy.yaml",
)
META_INPUTS = (
    *MOUNTED_META_INPUTS,
    "reference/pipeline.mmd",
    "architecture/freshness.md",
)
REDIRECTS = REPO / "data/redirects.yaml"
DIAGRAM_SOURCE = REPO.parent / "anomalica/reference/pipeline.mmd"
DIAGRAM_SVG = REPO / "assets/architecture/pipeline.svg"
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


def unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject ambiguous JSON objects instead of silently keeping the last key."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def guarded_inherited_groups(
    path: Path,
    expected_sha256: str,
    reason_codes: dict[str, set[str]] | None = None,
) -> list[dict]:
    """Load an explicit freshness input only when its exact bytes are authorised."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise DeployError("inherited freshness SHA-256 must be 64 hexadecimal digits")
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256.lower():
        raise DeployError(
            f"inherited freshness SHA-256 mismatch: expected {expected_sha256.lower()}, "
            f"got {actual}"
        )
    try:
        manifest = json.loads(payload, object_pairs_hook=unique_json_object)
        return inherited_groups_from_manifest(manifest, reason_codes)
    except (json.JSONDecodeError, ValueError) as exc:
        raise DeployError(f"invalid inherited freshness manifest: {exc}") from exc


def emit_deployment_freshness(**observations) -> dict:
    """Write and return one canonical result without changing failure handling."""
    result = deployment_freshness_result(**observations)
    log("Deployment freshness result")
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


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


def flatten(markup: str) -> str:
    """One line of plain text from a rendered label's markup.

    Mermaid draws labels as HTML inside foreignObject, so the text arrives
    wrapped in tags and with its entities escaped - a source label written
    "one -> many" renders as "one -&gt; many" and would otherwise read as a
    difference every time.
    """
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def check_diagram_current(diagram_source: Path, diagram_svg: Path) -> None:
    """Refuse to publish an architecture diagram that has drifted from its source.

    The diagram is authored in the meta-repo as mermaid and pre-rendered to SVG
    here, because rendering it needs a browser and the site must load no runtime
    mermaid. Nothing connects the two: a change to the source is only reflected
    when someone remembers to re-render, and one went unnoticed for seven weeks -
    the public page was missing a whole node of the pipeline.

    Compares node ids, node labels AND edge labels. Ids alone would have passed
    the drift that prompted this, which was a label change with no node change;
    nodes alone would have passed the next one, which changed two edge labels
    and no node at all. What a reader learns from this diagram is mostly in the
    edges - they are where the pipeline says what it hands on and under what
    terms - so an unchecked edge is the same seven-week silence in a smaller
    place.

    It reports; it does not re-render. Rendering needs a browser with the right
    font loaded, and a silent re-render at deploy time is how a clipped diagram
    ships without anyone looking at it.
    """
    if not diagram_source.is_file() or not diagram_svg.is_file():
        log("  diagram check skipped: source or rendered copy missing")
        return

    mermaid = diagram_source.read_text()
    source = dict(
        re.findall(
            r'^\s*(\w+)@\{\s*shape:\s*[\w-]+,\s*label:\s*"([^"]*)"',
            mermaid,
            re.M,
        )
    )
    # An edge label is the quoted text between the arrow and its target, in any
    # of the arrow forms this diagram uses (-->, -.->, ==>, <-->).
    source_edges = sorted(
        " ".join(label.split()) for label in re.findall(r'\|\s*"([^"]*)"\s*\|', mermaid)
    )

    svg = diagram_svg.read_text()
    # Node ids carry a render-order suffix that changes whenever the diagram
    # gains a node, so they are matched by name - as the page's own script does.
    starts = [
        (m.start(), m.group(1))
        for m in re.finditer(r'id="al-flowchart-(.+?)-\d+"', svg)
    ]
    rendered: dict[str, str] = {}
    for index, (position, node) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(svg)
        label = re.search(
            r'class="nodeLabel[^"]*"[^>]*>(.*?)</span>', svg[position:end], re.S
        )
        if label:
            rendered[node] = flatten(label.group(1))

    rendered_edges = sorted(
        text
        for text in (
            flatten(m.group(1))
            for m in re.finditer(r'class="edgeLabel"[^>]*>(.*?)</span>', svg, re.S)
        )
        if text
    )

    missing = sorted(set(source) - set(rendered))
    extra = sorted(set(rendered) - set(source))
    changed = sorted(
        f"{node}: rendered {rendered[node]!r}, source {source[node]!r}"
        for node in set(source) & set(rendered)
        if " ".join(source[node].split()) != rendered[node]
    )
    edges_lost = [label for label in source_edges if label not in rendered_edges]
    edges_stale = [label for label in rendered_edges if label not in source_edges]

    if not (missing or extra or changed or edges_lost or edges_stale):
        log(
            f"  diagram matches its source "
            f"({len(source)} nodes, {len(source_edges)} edge labels)"
        )
        return

    for node in missing:
        log(f"    in the source, not rendered: {node}")
    for node in extra:
        log(f"    rendered, not in the source: {node}")
    for line in changed:
        log(f"    label differs, {line}")
    for label in edges_lost:
        log(f"    edge label in the source, not rendered: {label!r}")
    for label in edges_stale:
        log(f"    edge label rendered, not in the source: {label!r}")
    raise DeployError(
        "the architecture diagram has drifted from anomalica/reference/pipeline.mmd. "
        "Re-render it per assets/architecture/README.md, look at the result, then deploy."
    )


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
    head = git("rev-parse", "HEAD")
    dirty = [line[2:].strip() for line in git("status", "--porcelain").splitlines()]
    return branch, head, dirty


def repository_commit(repository: Path) -> str:
    """Return the exact committed revision used as a build input."""
    return subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def snapshot_repository(repository: Path, destination: Path, revision: str) -> Path:
    """Export one exact committed tree without reading mutable source bytes."""
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / f"{destination.name}.tar"
    with archive.open("wb") as handle:
        subprocess.run(
            ["git", "-C", str(repository), "archive", revision],
            stdout=handle,
            check=True,
        )
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")
    archive.unlink()
    return destination


def committed_meta_inputs(destination: Path, revision: str) -> dict[str, str]:
    """Bind every mounted or validation input read from the meta repository."""
    snapshot_repository(META_REPO, destination, revision)
    hashes = {}
    for relative in META_INPUTS:
        try:
            committed = subprocess.run(
                ["git", "-C", str(META_REPO), "show", f"{revision}:{relative}"],
                capture_output=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError:
            raise DeployError(f"committed meta input is missing: {relative}")
        working = META_REPO / relative
        if not working.is_file() or working.read_bytes() != committed:
            raise DeployError(f"meta input differs from {revision}: {relative}")
        snapshot = destination / relative
        if not snapshot.is_file() or snapshot.read_bytes() != committed:
            raise DeployError(f"meta snapshot mismatch: {relative}")
        hashes[relative] = hashlib.sha256(committed).hexdigest()
    return hashes


def committed_reason_codes(meta_source: Path) -> dict[str, set[str]]:
    """Read the reason vocabulary from the same immutable meta snapshot."""
    path = meta_source / "architecture/freshness.md"
    if not path.is_file():
        raise DeployError("committed freshness architecture is missing")
    try:
        return reason_code_contract(path.read_text())
    except ValueError as exc:
        raise DeployError(f"invalid committed freshness architecture: {exc}") from exc


def snapshot_content(
    destination: Path, revision: str | None = None
) -> tuple[Path, str]:
    """Export the content repo at HEAD, and build against that instead of the tree.

    The build MOUNTS this repository, so without this it publishes whatever is on
    disk at the moment hugo runs - a page the assembler is halfway through
    writing, or whichever branch happens to be checked out. Neither shows up in a
    build log. Exporting HEAD means a deploy always publishes a committed state
    and the assembler can keep working while it runs.
    """
    branch, head, dirty = content_state()
    revision = revision or head
    snapshot_repository(CONTENT_REPO, destination, revision)
    uncommitted = f" ({len(dirty)} uncommitted, not published)" if dirty else ""
    log(f"Content repo {branch} at {revision}{uncommitted}")
    return destination, revision


# --- build -------------------------------------------------------------------


def module_override(
    site_source: Path, content_source: Path, meta_source: Path, path: Path
) -> Path:
    """A second config that re-points the content mounts at the snapshot.

    Generated from the project's own mounts rather than restated, so it keeps
    working when hugo.toml changes.
    """
    import tomllib

    config = tomllib.loads((site_source / "hugo.toml").read_text())
    lines = ["[module]"]
    mounted_meta_inputs = set()
    for mount in config.get("module", {}).get("mounts", []):
        source = mount["source"]
        if source.startswith("../content/"):
            source = str(content_source / source[len("../content/") :])
        elif source.startswith("../anomalica/"):
            relative = source[len("../anomalica/") :]
            mounted_meta_inputs.add(relative)
            source = str(meta_source / relative)
        lines.append("[[module.mounts]]")
        for key, value in mount.items():
            rendered = f'"{source}"' if key == "source" else json.dumps(value)
            lines.append(f"{key} = {rendered}")
    if mounted_meta_inputs != set(MOUNTED_META_INPUTS):
        raise DeployError(
            "direct meta mounts do not match the hash-bound input set: "
            f"expected {sorted(MOUNTED_META_INPUTS)}, got {sorted(mounted_meta_inputs)}"
        )
    path.write_text("\n".join(lines) + "\n")
    return path


def build(
    destination: Path, site_source: Path, content_source: Path, meta_source: Path
) -> None:
    log(f"Building into {destination}")
    subprocess.run(
        ["bash", str(site_source / "scripts/fetch-vendor.sh")],
        cwd=site_source,
        check=True,
    )
    # Briefs are converted from the SNAPSHOT, not the working tree: the tree
    # holds briefs the assembler is still writing.
    subprocess.run(
        [
            sys.executable,
            str(site_source / "scripts/briefs-to-json.py"),
            str(content_source / "briefs"),
        ],
        cwd=site_source,
        check=True,
    )
    # The committed compiled.css is the readable build the dev server watches.
    # Minifying writes over it in place, so it is put back afterwards: a deploy
    # must not leave the working tree dirty.
    stylesheet = site_source / "assets/css/compiled.css"
    dependencies = site_source / "node_modules"
    linked_dependencies = not dependencies.exists()
    if linked_dependencies:
        dependencies.symlink_to(REPO / "node_modules", target_is_directory=True)
    try:
        subprocess.run(
            [
                str(REPO / "node_modules/.bin/tailwindcss"),
                "-i",
                "assets/css/main.css",
                "-o",
                "assets/css/compiled.css",
                "--minify",
            ],
            cwd=site_source,
            check=True,
        )
        # -e production is load-bearing: without it hugo.IsProduction is false in
        # this environment and templates render their development branch.
        override = module_override(
            site_source,
            content_source,
            meta_source,
            destination.parent / "mounts.toml",
        )
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
            cwd=site_source,
            check=True,
        )
    finally:
        stylesheet.unlink(missing_ok=True)
        if linked_dependencies:
            dependencies.unlink(missing_ok=True)


def apply_redirects(build_dir: Path, redirects: Path = REDIRECTS) -> None:
    """Write a redirect for every retired URL that no longer has a page.

    Hugo's own aliases live in the destination page's front matter, which the
    assembler regenerates on every write - so they can only carry a slug that
    entity itself once had. A page merged INTO a different entity leaves a URL
    no front matter will ever claim, and hand-adding one there has been undone
    by a rebuild before. These live in this repo instead.

    Skipped while a real page still occupies the path: an entry can be added
    before the page is removed, and starts working by itself when it goes.
    """
    if not redirects.is_file():
        return
    entries = (yaml.safe_load(redirects.read_text()) or {}).get("redirects") or []
    written = skipped = 0
    for entry in entries:
        # A retired URL with nowhere to send readers is recorded here too, so
        # the removal is a decision on the record rather than a flag someone
        # remembers to pass. It gets no redirect file: the page simply goes.
        # Whether a page recorded here has come BACK is checked separately, by
        # check_resurrected, which needs the live listing to tell a page that
        # was never retired from one that was and has returned.
        if entry.get("gone"):
            continue
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

    redirect_flat_briefs(build_dir)


def redirect_flat_briefs(build_dir: Path) -> None:
    """Point the old flat brief URLs at their sectioned ones.

    Brief URLs gained their section when AARO turned up as both an organisation
    and a project, so a flat URL served one and silently dropped the other. The
    old URLs are derived rather than listed - one per brief, 800 of them, and a
    hand-written list would be a lie the moment a brief is added.

    A slug that appears in more than one section gets NO redirect: it is exactly
    the ambiguity that forced the move, and guessing which one a reader wanted
    is the wrong kind of helpful.
    """
    briefs = build_dir / "en/briefs"
    if not briefs.is_dir():
        return
    sections: dict[str, list[str]] = {}
    for page in briefs.glob("*/*/index.html"):
        sections.setdefault(page.parent.name, []).append(page.parent.parent.name)

    written = ambiguous = 0
    for slug, found in sections.items():
        flat = briefs / slug / "index.html"
        if len(found) > 1:
            ambiguous += 1
            continue
        if flat.exists():
            continue
        target = f"/en/briefs/{found[0]}/{slug}/"
        flat.parent.mkdir(parents=True, exist_ok=True)
        flat.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{LIVE_ORIGIN}{target}</title>"
            f'<link rel="canonical" href="{LIVE_ORIGIN}{target}">'
            '<meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={target}">'
            f'</head><body><a href="{target}">{LIVE_ORIGIN}{target}</a></body></html>'
        )
        written += 1
    log(
        f"  {written} flat brief URL(s) redirected to their section"
        + (f", {ambiguous} ambiguous and left to 404" if ambiguous else "")
    )


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


def verify_no_dead_links(build_dir: Path) -> dict[str, set[str]]:
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
    else:
        log(f"  no dead internal links across {len(pages)} pages")
    return dead


def built_aliases(build_dir: Path) -> list[str]:
    """Return canonical paths for redirects emitted by the production build."""
    return sorted(
        "/" + str(page.parent.relative_to(build_dir)) + "/"
        for page in build_dir.rglob("index.html")
        if "http-equiv=refresh" in page.read_text(errors="replace")[:600]
    )


def report_alias_changes(
    build_dir: Path, persist: bool, redirects: Path = REDIRECTS
) -> list[str]:
    """Name any redirect that has stopped being built.

    Aliases live in a page's front matter, so a rebuild of that page silently
    drops them - and because the build no longer emits the redirect, the deploy
    dutifully deletes it and a URL that worked an hour ago starts 404ing. That
    has happened once already, to /people/david-grusch/ and /organisations/nasa/.
    Nothing else reports it: the alias is not a page, so no page count changes.
    """
    current = built_aliases(build_dir)
    previous = read_state().get("aliases", [])
    acknowledged = {
        "/" + name[: -len("index.html")] for name in retired_urls(redirects)
    }
    dropped = [
        alias
        for alias in previous
        if alias not in current and alias not in acknowledged
    ]
    if dropped:
        log(f"  WARNING: {len(dropped)} redirect(s) no longer built - these will 404:")
        for alias in dropped:
            log(f"    {alias}")
    log(f"  {len(current)} redirect(s) in the build")
    if persist:
        write_state("aliases", current)
    return dropped


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
    site_source: Path = REPO,
    persist: bool = False,
    limit: int = 15,
) -> dict[str, int]:
    """Count internal links the templates had to strip for want of a page.

    These never reach the HTML - the markdown link hook renders them as plain
    text when the target does not exist - so the dead-link assertion above
    cannot see them. This is the number that measures assembly progress: it
    should fall as entity pages land, and a rise means the assembler is
    emitting links to pages nobody is building.
    """
    roots = (
        (site_source / "content/english", content_source / "pages")
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
    return counts


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


def retired_urls(redirects: Path = REDIRECTS) -> set[str]:
    """URLs recorded as intentionally gone, with no replacement."""
    if not redirects.is_file():
        return set()
    entries = (yaml.safe_load(redirects.read_text()) or {}).get("redirects") or []
    return {e["from"].strip("/") + "/index.html" for e in entries if e.get("gone")}


def check_resurrected(local: dict, remote: dict, redirects: Path = REDIRECTS) -> None:
    """Refuse to republish a page that was retired on the record.

    A page is retired by deleting its source, but the brief it was written from
    stays on disk, so a later run that does not know about the retirement builds
    it again. It then reappears looking exactly like a page that was never
    retired - the decision is undone and nothing says so.

    Being in the build is not enough to know that, because an entry is recorded
    BEFORE the page is removed - that ordering is what check_removals enforces -
    so between the record and the removal the page is legitimately still built
    and still served. The live listing tells the two apart: a retired URL that
    is still on the CDN has not been taken down yet, while one that is gone from
    the CDN and back in the build has returned from the dead.
    """
    back = sorted(
        url for url in retired_urls(redirects) if url in local and url not in remote
    )
    if not back:
        return
    for url in back:
        log(f"    retired on the record, but built again: /{url[: -len('index.html')]}")
    raise DeployError(
        f"{len(back)} page(s) recorded as retired in data/redirects.yaml have been "
        "built again after being taken down. Publishing them would undo a recorded "
        "decision without anyone saying so. Either find out what rebuilt them, or - "
        "if they are meant to be back - remove their entries, so the un-retirement "
        "is a decision on the record in the way the retirement was."
    )


def currently_serves(path: str) -> str:
    """What the live site answers with at this path, for a refusal message.

    A removal is never one URL: it is the page's own path, every alias the page
    carried, and both language forms of each. The orphan list names them all,
    but names alone do not say WHICH is which - and an alias of a page already
    recorded needs a line of its own while looking identical to a page nobody
    has considered. Asking the live site closes that gap, because an alias
    answers with a redirect naming its target and a real page does not.

    Best effort. A failed lookup returns "" and the refusal reads as it did
    before, because this is here to explain a refusal rather than to cause one.
    """
    try:
        with urllib.request.urlopen(f"{LIVE_ORIGIN}/{path}", timeout=10) as response:
            body = response.read(2048).decode("utf-8", "replace")
    except Exception:
        return ""
    match = re.search(r'http-equiv="?refresh"?[^>]*url=([^"\'>\s]+)', body, re.I)
    return f"redirects to {match.group(1)}" if match else "a page in its own right"


def check_removals(
    orphaned: list[str],
    build_dir: Path,
    accept: bool,
    redirects: Path = REDIRECTS,
) -> None:
    """Refuse to turn a live page into a 404 without saying so out loud.

    Deleting what the build no longer produces is right for a renamed asset and
    wrong for a page: the URL is in search results and in other people's links.
    A page that was merged away should leave a redirect behind, which means the
    entry has to exist BEFORE the page is pruned - and the reverse order fails
    silently, because a 404 nobody visits is a 404 nobody reports. This makes
    the order impossible to get wrong by accident rather than asking people to
    remember it.

    A page that is genuinely retired with nowhere to send its readers is a real
    case, so it passes with --accept-404s.
    """
    retired = retired_urls(redirects)
    # Brief pages are exempt, and only brief pages. They are generated per graph
    # node, so they appear and vanish as the graph is merged and pruned - 42 in
    # one deploy - and blocking on each would train whoever runs this to pass
    # --accept-404s by reflex, which is the guard's own failure mode. They are
    # safe to lose: nothing links to one except its article, and that link is
    # existence-gated, so it degrades to "the brief has not been published"
    # rather than a dead link. An ARTICLE url is the thing a reader keeps.
    briefs = {
        name
        for name in orphaned
        if name.startswith("en/briefs/") and name.endswith("index.html")
    }
    if briefs:
        log(f"  {len(briefs)} brief page(s) removed with their graph nodes")
    pages = [
        name
        for name in orphaned
        if name.endswith("index.html") and name not in retired and name not in briefs
    ]
    acknowledged = [name for name in orphaned if name in retired]
    for name in acknowledged:
        log(
            f"  retiring /{name[: -len('index.html')]} as recorded in data/redirects.yaml"
        )
    if not pages:
        return
    log(f"  {len(pages)} live page(s) would stop existing:")
    # Say what each one answers with today. The names alone cannot distinguish
    # an alias of a page already recorded from a page nobody has considered,
    # and recording one and not the other costs a whole deploy cycle.
    for name in pages[:25]:
        path = name[: -len("index.html")]
        serving = currently_serves(path)
        log(f"    /{path}{f'   ({serving})' if serving else ''}")
    if len(pages) > 25:
        log(f"    ... {len(pages) - 25} more")
    if accept:
        log("  proceeding (--accept-404s)")
        return
    raise DeployError(
        f"{len(pages)} page(s) would start returning 404. Add each to "
        "data/redirects.yaml - with a target if something replaced it, or "
        "gone: true and a note if nothing did - or pass --accept-404s for a "
        "one-off."
    )


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
) -> dict[str, bool]:
    """Assert the live page IS the page just built, not merely that it answers.

    A status code cannot tell "deployed and propagated" from "deployed, not yet
    visible": a purge takes a few seconds to reach every edge, and a check that
    runs immediately reads the old page and calls it a success - or, if it looks
    for new content, calls a working deploy a failure. Comparing the body hash
    against the built file answers exactly, and retrying covers the window.
    """
    samples: dict[str, bool] = {}
    for path in paths:
        url = f"{LIVE_ORIGIN}{path}"
        local = build_dir / path.strip("/") / "index.html"
        expected = (
            hashlib.sha256(local.read_bytes()).hexdigest() if local.is_file() else None
        )
        for attempt in range(1, attempts + 1):
            status = None
            served = None
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    status = response.status
                    served = hashlib.sha256(response.read()).hexdigest()
            except urllib.error.HTTPError as exc:
                status = exc.code
            except OSError:
                pass
            if status == 200 and (expected is None or served == expected):
                log(f"  {status}  {url}")
                samples[path] = True
                break
            if attempt == attempts:
                samples[path] = False
                break
            time.sleep(wait)
    return samples


# --- entry point -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="build and verify only")
    parser.add_argument(
        "--keep-build", action="store_true", help="do not remove the build directory"
    )
    parser.add_argument(
        "--accept-404s",
        action="store_true",
        help="allow removed pages to 404 rather than redirect",
    )
    parser.add_argument(
        "--inherited-freshness",
        type=Path,
        help="JSON manifest of upstream freshness reason groups",
    )
    parser.add_argument(
        "--inherited-freshness-sha256",
        help="required exact SHA-256 guard for --inherited-freshness",
    )
    args = parser.parse_args()

    workspace: Path | None = None
    build_dir: Path | None = None
    site_source: Path | None = None
    site_commit = None
    content_commit = None
    meta_commit = None
    meta_input_hashes: dict[str, str] = {}
    reason_codes: dict[str, set[str]] | None = None
    local_hashes: dict[str, str] = {}
    remote: dict[str, str] | None = None
    dead_links: dict[str, set[str]] = {}
    stripped_links: dict[str, int] = {}
    dropped_redirects: list[str] = []
    live_samples: dict[str, bool] | None = None
    inherited_groups: list[dict] = []
    inherited_source: dict[str, str] | None = None
    build_failed = False
    publication_started = False
    storage_key = None
    stage = "input"
    try:
        commit_error = None
        try:
            site_commit = repository_commit(REPO)
        except Exception as exc:
            commit_error = exc
        try:
            content_commit = repository_commit(CONTENT_REPO)
        except Exception as exc:
            commit_error = commit_error or exc
        try:
            meta_commit = repository_commit(META_REPO)
        except Exception as exc:
            commit_error = commit_error or exc
        if commit_error:
            raise commit_error

        stage = "workspace"
        workspace = Path(tempfile.mkdtemp(prefix="anomalica-site-"))
        build_dir = workspace / "site"
        site_source = snapshot_repository(REPO, workspace / "site-source", site_commit)
        meta_source = workspace / "anomalica"
        meta_input_hashes = committed_meta_inputs(meta_source, meta_commit)
        reason_codes = committed_reason_codes(meta_source)

        if bool(args.inherited_freshness) != bool(args.inherited_freshness_sha256):
            raise DeployError(
                "--inherited-freshness and --inherited-freshness-sha256 must be used together"
            )
        if args.inherited_freshness:
            inherited_groups = guarded_inherited_groups(
                args.inherited_freshness,
                args.inherited_freshness_sha256,
                reason_codes,
            )
            inherited_source = {
                "path": str(args.inherited_freshness.resolve()),
                "sha256": args.inherited_freshness_sha256.lower(),
            }

        stage = "build"
        build_failed = True
        check_diagram_current(
            meta_source / "reference/pipeline.mmd",
            site_source / "assets/architecture/pipeline.svg",
        )
        content_source, archived_commit = snapshot_content(
            workspace / "content", content_commit
        )
        content_commit = archived_commit
        build(build_dir, site_source, content_source, meta_source)
        redirects = site_source / "data/redirects.yaml"
        apply_redirects(build_dir, redirects)
        log("Verifying the build")
        verify_assets_fingerprinted(build_dir)
        build_failed = False

        stage = "validation"
        dead_links = verify_no_dead_links(build_dir)
        if dead_links:
            raise DeployError(
                f"{len(dead_links)} dead internal link target(s); refusing to deploy"
            )
        stripped_links = report_unresolved_links(
            build_dir,
            content_source=content_source,
            site_source=site_source,
            persist=False,
        )
        dropped_redirects = report_alias_changes(
            build_dir, persist=False, redirects=redirects
        )

        stage = "remote-state"
        storage_key = secret("BUNNY_SITE_STORAGE_PASSWORD")
        local = local_files(build_dir)
        remote = remote_files(storage_key)

        local_hashes = {name: digest for name, (_, digest) in local.items()}
        changed = [
            name for name, digest in local_hashes.items() if remote.get(name) != digest
        ]
        orphaned = sorted(set(remote) - set(local))
        log(
            f"{len(local)} files built; {len(changed)} new or changed, "
            f"{len(orphaned)} to remove"
        )

        check_resurrected(local, remote, redirects)
        check_removals(orphaned, build_dir, args.accept_404s, redirects)

        if args.dry_run:
            for name in sorted(changed)[:40]:
                log(f"  would upload {name}")
            for name in orphaned[:40]:
                log(f"  would delete {name}")
            emit_deployment_freshness(
                site_commit=site_commit,
                content_commit=content_commit,
                meta_commit=meta_commit,
                meta_input_hashes=meta_input_hashes,
                local_hashes=local_hashes,
                remote_hashes=remote,
                dead_links=dead_links,
                stripped_links=stripped_links,
                dropped_redirects=dropped_redirects,
                live_samples=None,
                inherited_groups=inherited_groups,
                inherited_source=inherited_source,
                reason_codes=reason_codes,
            )
            return 0

        stage = "publish"
        publication_started = True
        if changed:
            in_parallel(lambda name: upload(storage_key, name, local[name][0]), changed)
            log(f"  uploaded {len(changed)}")
        if orphaned:
            in_parallel(lambda name: delete(storage_key, name), orphaned)
            log(f"  deleted {len(orphaned)}")

        if changed or orphaned:
            remote = remote_files(storage_key)
            if remote != local_hashes:
                raise DeployError(
                    "remote storage does not match the verified build after publish"
                )

        if changed or orphaned:
            purge(secret("BUNNY_API_KEY"))
            checks = ["/en/"] + [
                "/" + name.rsplit("/index.html", 1)[0] + "/"
                for name in sorted(changed)
                if name.endswith("/index.html")
            ][:3]
            log("Verifying live")
            stage = "live-validation"
            live_samples = verify_live(build_dir, checks)
            mismatches = [path for path, matches in live_samples.items() if not matches]
            if mismatches:
                url = f"{LIVE_ORIGIN}{mismatches[0]}"
                raise DeployError(
                    f"{url} answers but does not match the build after 30s - "
                    "the purge did not take"
                )
        else:
            log("Nothing to publish; the zone already matches the build")
        write_state("targets", stripped_links)
        write_state("aliases", built_aliases(build_dir))
        emit_deployment_freshness(
            site_commit=site_commit,
            content_commit=content_commit,
            meta_commit=meta_commit,
            meta_input_hashes=meta_input_hashes,
            local_hashes=local_hashes,
            remote_hashes=remote,
            dead_links=dead_links,
            stripped_links=stripped_links,
            dropped_redirects=dropped_redirects,
            live_samples=live_samples,
            inherited_groups=inherited_groups,
            inherited_source=inherited_source,
            reason_codes=reason_codes,
        )
        return 0
    except Exception as exc:
        if publication_started and storage_key:
            try:
                remote = remote_files(storage_key)
            except Exception:
                remote = None
        try:
            emit_deployment_freshness(
                site_commit=site_commit,
                content_commit=content_commit,
                meta_commit=meta_commit,
                meta_input_hashes=meta_input_hashes,
                local_hashes=local_hashes,
                remote_hashes=remote,
                dead_links=dead_links,
                stripped_links=stripped_links,
                dropped_redirects=dropped_redirects,
                live_samples=live_samples,
                inherited_groups=inherited_groups,
                inherited_source=inherited_source,
                reason_codes=reason_codes,
                build_failed=build_failed,
                failure={
                    "stage": stage,
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            )
        except Exception as result_exc:
            print(
                f"could not construct deployment freshness result: {result_exc}",
                file=sys.stderr,
            )
        print(f"deploy failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.keep_build and build_dir is not None:
            log(f"build left at {build_dir}")
        elif workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
