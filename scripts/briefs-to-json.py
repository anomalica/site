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
        digest = hashlib.sha256(raw).hexdigest()
        cached = index.get(str(brief.relative_to(source)))
        section = brief.parent.name if brief.parent != source else None
        data = None
        if section is None:
            data = yaml.safe_load(raw.decode(errors="replace"))
            section = SECTION_OF.get(((data or {}).get("page") or {}).get("node_type"))
            if section is None:
                unplaced.append(brief.name)
                continue
        out = TARGET / section / f"{brief.stem}.json"
        seen.add(f"{section}/{out.name}")
        if out.exists() and cached == digest:
            continue
        if data is None:
            data = yaml.safe_load(raw.decode(errors="replace"))
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
