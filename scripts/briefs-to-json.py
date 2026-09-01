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
"""

from __future__ import annotations

import json
import pathlib
import sys

import yaml

DEFAULT_SOURCE = (
    pathlib.Path(__file__).resolve().parent.parent.parent / "content/briefs"
)
TARGET = pathlib.Path(__file__).resolve().parent.parent / ".briefs-json"


def main() -> int:
    # The deploy builds from a snapshot of the content repo at HEAD, so it
    # passes that path: converting the working tree there would publish briefs
    # that are still being written.
    source = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.is_dir():
        print(f"no briefs at {source}", file=sys.stderr)
        return 1
    TARGET.mkdir(exist_ok=True)

    seen = set()
    converted = 0
    for brief in sorted(source.glob("*.yaml")):
        out = TARGET / f"{brief.stem}.json"
        seen.add(out.name)
        if out.exists() and out.stat().st_mtime >= brief.stat().st_mtime:
            continue
        data = yaml.safe_load(brief.read_text(errors="replace"))
        out.write_text(json.dumps(data, default=str, ensure_ascii=False))
        converted += 1

    # A brief that has been deleted must not linger as a page.
    removed = 0
    for stale in TARGET.glob("*.json"):
        if stale.name not in seen:
            stale.unlink()
            removed += 1

    print(f"briefs: {converted} converted, {removed} removed, {len(seen)} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
