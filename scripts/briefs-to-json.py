#!/usr/bin/env python3
"""Mirror the brief files to JSON for Hugo to read as data.

Hugo cannot load the largest briefs as YAML. Its parser (go-yaml v3) applies a
billion-laughs guard that misfires on big documents, and refuses a 3.5MB brief
with "too many YAML aliases for non-scalar nodes" - the files contain no
aliases at all. Measured: 2.1MB loads, 3.5MB does not. The same data as JSON
loads fine at 3.6MB and renders all 2,457 claims, so the fix is the format Hugo
reads, not the format the pipeline writes.

Converting here rather than asking for a second emission keeps one source of
truth in the content repo. Unchanged files are skipped, so this costs nothing
after the first run.

The output mirrors the page's own two halves - .briefs-json/<section>/<slug>
- because a slug is only unique WITHIN a section: an event and a project can
both be called "Apollo 14". The source is moving to the same shape; until it
does, the section is taken from the brief's own node type, so both layouts
convert to the same output and the move changes nothing here.

The brief's stored page title is replaced with the article's own, because the
stored one is a snapshot of the name the article had when the brief was
written. Rename an article and the brief goes on heading itself, and labelling
its own link to the article, with a name the article no longer uses. Hugo
cannot do this substitution itself: the pages do not exist yet while the
content adapter that creates the brief pages is running. A brief whose article
was never assembled keeps its stored title, which is all there is.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import yaml

DEFAULT_SOURCE = (
    pathlib.Path(__file__).resolve().parent.parent.parent / "content/briefs"
)
TARGET = pathlib.Path(__file__).resolve().parent.parent / ".briefs-json"


def article_title(pages: pathlib.Path, section: str, slug: str) -> str | None:
    """The name the article gives itself, or None if it was never assembled."""
    article = pages / section / f"{slug}.en.md"
    try:
        text = article.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        front = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    title = (front or {}).get("title")
    return title if isinstance(title, str) and title else None


# A node type names a thing; a section names where its pages live.
SECTION_OF = {
    "person": "people",
    "organisation": "organisations",
    "event": "events",
    "project": "projects",
    "object": "objects",
    "place": "places",
    "topic": "topics",
    "document": "documents",
}


def main() -> int:
    # The deploy builds from a snapshot of the content repo at HEAD, so it
    # passes that path: converting the working tree there would publish briefs
    # that are still being written.
    source = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.is_dir():
        print(f"no briefs at {source}", file=sys.stderr)
        return 1
    # The articles sit beside the briefs in the same repo, and in the deploy's
    # case in the same snapshot, so the pages a brief is named after are always
    # the ones this conversion is being run against.
    pages = source.parent / "pages"
    TARGET.mkdir(exist_ok=True)

    # Keyed on CONTENT, not mtime: the deploy converts a fresh git snapshot
    # whose files carry the commit's timestamps, so an mtime comparison would
    # call an older-looking snapshot up to date and publish whatever happened
    # to be converted last.
    index_file = TARGET / ".source-hashes.json"
    index = json.loads(index_file.read_text()) if index_file.is_file() else {}

    seen = set()
    converted = 0
    unplaced = []
    # Both layouts: <slug>.yaml today, <section>/<slug>.yaml after the move.
    for brief in sorted([*source.glob("*.yaml"), *source.glob("*/*.yaml")]):
        # The pipeline writes into this directory while we read it, so a file
        # listed a moment ago can be gone by the time we open it.
        try:
            raw = brief.read_bytes()
        except FileNotFoundError:
            continue
        cached = index.get(str(brief.relative_to(source)))
        section = brief.parent.name if brief.parent != source else None
        data = None
        if section is None:
            data = yaml.safe_load(raw.decode(errors="replace"))
            section = SECTION_OF.get(((data or {}).get("page") or {}).get("node_type"))
            if section is None:
                unplaced.append(brief.name)
                continue
        # The article's name is part of what this converts, so a rename has to
        # invalidate the cache the same way an edit to the brief itself does.
        title = article_title(pages, section, brief.stem)
        digest = hashlib.sha256(raw + b"\0" + (title or "").encode()).hexdigest()
        out = TARGET / section / f"{brief.stem}.json"
        seen.add(f"{section}/{out.name}")
        if out.exists() and cached == digest:
            continue
        if data is None:
            data = yaml.safe_load(raw.decode(errors="replace"))
        if title:
            page = (data or {}).get("page")
            if isinstance(page, dict):
                page["title"] = title
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, default=str, ensure_ascii=False))
        index[str(brief.relative_to(source))] = digest
        converted += 1
    index_file.write_text(json.dumps(index, indent=0, sort_keys=True))

    # A brief that has been deleted must not linger as a page.
    removed = 0
    for stale in TARGET.glob("*/*.json"):
        if f"{stale.parent.name}/{stale.name}" not in seen:
            stale.unlink()
            removed += 1
    for orphan in TARGET.glob("*.json"):
        # Left by the flat layout this script used to write.
        if orphan.name != index_file.name:
            orphan.unlink()
            removed += 1

    if unplaced:
        print(
            f"WARNING: {len(unplaced)} brief(s) with no known node type: {unplaced[:5]}",
            file=sys.stderr,
        )
    print(f"briefs: {converted} converted, {removed} removed, {len(seen)} total")
    return 1 if unplaced else 0


if __name__ == "__main__":
    sys.exit(main())
