"""Pure construction of the ADR 0050 deployment freshness result."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path


STATUS_RANK = {"current": 0, "missing": 1, "unknown": 2, "stale": 3, "invalid": 4}
CONSEQUENCE_RANK = {"new": 0, "verify": 1, "finish": 2, "repair": 3}
MANIFEST_FIELDS = {"schema", "generated_at", "source_queue_sha256", "groups"}
GROUP_FIELDS = {
    "boundary",
    "artifact",
    "local_status",
    "local_reasons",
    "inherited",
    "consequence",
}
HASH_ARTIFACT_BOUNDARIES = {"record-generation", "digest-input", "graph-import"}
FRESHNESS_ARCHITECTURE = (
    Path(__file__).resolve().parents[2] / "anomalica/architecture/freshness.md"
)


def reason_code_contract(document: str) -> dict[str, set[str]]:
    """Extract boundary-specific reason placements from the canonical spec."""
    try:
        section = document.split("Reason codes are", 1)[1].split(
            "Several codes may coexist", 1
        )[0]
    except IndexError as exc:
        raise ValueError("canonical freshness reason-code section is missing") from exc
    contract = {
        match.group(1): set(re.findall(r"`([^`]+)`", match.group(2)))
        for match in re.finditer(r"^- `([^`]+)`: (.*?)(?:;|\.)$", section, re.M | re.S)
    }
    if "deployment" not in contract or any(
        not reasons for reasons in contract.values()
    ):
        raise ValueError("canonical freshness reason-code section is malformed")
    return contract


def canonical_reason_code_contract() -> dict[str, set[str]]:
    """Load reason placements from the architecture source used by this workspace."""
    try:
        return reason_code_contract(FRESHNESS_ARCHITECTURE.read_text())
    except OSError as exc:
        raise ValueError(
            f"canonical freshness architecture is unavailable: {FRESHNESS_ARCHITECTURE}"
        ) from exc


def deduplicate_reason_groups(
    groups: Iterable[dict], reason_codes: dict[str, set[str]] | None = None
) -> list[dict]:
    """Validate and union reason groups, including nested inherited groups."""
    groups = list(groups)
    if not groups:
        return []
    merged: dict[tuple[str, str], dict] = {}
    reason_codes = reason_codes or canonical_reason_code_contract()

    def add(group: dict) -> None:
        if not isinstance(group, dict):
            raise ValueError("freshness groups must be objects")
        boundary = group.get("boundary")
        artifact = group.get("artifact")
        status = group.get("local_status")
        consequence = group.get("consequence")
        reasons = group.get("local_reasons")
        inherited = group.get("inherited", [])
        if not isinstance(boundary, str) or not boundary:
            raise ValueError("freshness group boundary must be a non-empty string")
        if boundary not in reason_codes or boundary == "deployment":
            raise ValueError(f"invalid inherited freshness boundary: {boundary!r}")
        if not isinstance(artifact, str) or not artifact:
            raise ValueError("freshness group artifact must be a non-empty string")
        if status not in STATUS_RANK:
            raise ValueError(f"invalid freshness local_status: {status!r}")
        if consequence not in CONSEQUENCE_RANK:
            raise ValueError(f"invalid freshness consequence: {consequence!r}")
        if (
            not isinstance(reasons, list)
            or not reasons
            or not all(isinstance(reason, str) and reason for reason in reasons)
        ):
            raise ValueError("freshness group local_reasons must be non-empty strings")
        invalid_reasons = sorted(set(reasons) - reason_codes[boundary])
        if invalid_reasons:
            raise ValueError(
                f"invalid {boundary} reason code(s): {', '.join(invalid_reasons)}"
            )
        if not isinstance(inherited, list):
            raise ValueError("freshness group inherited must be a list")

        key = (boundary, artifact)
        current = merged.get(key)
        if current is None:
            merged[key] = {
                "boundary": boundary,
                "artifact": artifact,
                "local_status": status,
                "local_reasons": sorted(set(reasons)),
                "inherited": [],
                "consequence": consequence,
            }
        else:
            current["local_reasons"] = sorted(
                set(current["local_reasons"]) | set(reasons)
            )
            if STATUS_RANK[status] > STATUS_RANK[current["local_status"]]:
                current["local_status"] = status
            if CONSEQUENCE_RANK[consequence] > CONSEQUENCE_RANK[current["consequence"]]:
                current["consequence"] = consequence
        for inherited_group in inherited:
            add(inherited_group)

    for candidate in groups:
        add(candidate)
    return [merged[key] for key in sorted(merged)]


def inherited_groups_from_manifest(
    manifest: object, reason_codes: dict[str, set[str]] | None = None
) -> list[dict]:
    """Read canonical upstream groups from an explicitly guarded manifest."""
    if not isinstance(manifest, dict):
        raise ValueError("freshness manifest must be an object")
    if manifest.get("schema") != "anomalica-freshness/v1":
        raise ValueError("freshness manifest schema must be anomalica-freshness/v1")
    if set(manifest) != MANIFEST_FIELDS:
        missing = sorted(MANIFEST_FIELDS - set(manifest))
        unknown = sorted(set(manifest) - MANIFEST_FIELDS)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown: {', '.join(unknown)}")
        raise ValueError(f"invalid freshness manifest fields ({'; '.join(details)})")
    if (
        not isinstance(manifest.get("generated_at"), str)
        or not manifest["generated_at"]
    ):
        raise ValueError("freshness manifest generated_at must be a non-empty string")
    source_queue_sha256 = manifest.get("source_queue_sha256")
    if not isinstance(source_queue_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source_queue_sha256
    ):
        raise ValueError(
            "freshness manifest source_queue_sha256 must be 64 lowercase hexadecimal digits"
        )
    groups = manifest.get("groups")
    if not isinstance(groups, list):
        raise ValueError("freshness manifest groups must be a list")
    keys = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError(f"freshness manifest group {index} must be an object")
        if set(group) != GROUP_FIELDS:
            missing = sorted(GROUP_FIELDS - set(group))
            unknown = sorted(set(group) - GROUP_FIELDS)
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown: {', '.join(unknown)}")
            raise ValueError(
                f"invalid freshness manifest group {index} fields "
                f"({'; '.join(details)})"
            )
        if group["inherited"] != []:
            raise ValueError(
                f"freshness manifest group {index} inherited must be exactly []"
            )
        boundary = group["boundary"]
        artifact = group["artifact"]
        if group["local_status"] == "current":
            raise ValueError(
                f"freshness manifest group {index} cannot carry reasons with current status"
            )
        if boundary in HASH_ARTIFACT_BOUNDARIES:
            valid_artifact = isinstance(artifact, str) and bool(
                re.fullmatch(r"sha256:[0-9a-f]{64}", artifact)
            )
        elif boundary == "digest-generation":
            valid_artifact = (
                isinstance(artifact, str)
                and not artifact.startswith("/")
                and artifact.endswith(".yaml")
                and "\\" not in artifact
                and not ({"", ".", ".."} & set(Path(artifact).parts))
            )
        elif boundary == "brief-selection":
            valid_artifact = (
                isinstance(artifact, str)
                and bool(re.fullmatch(r"[^/]+/[^/.]+", artifact))
                and "\\" not in artifact
                and not ({".", ".."} & set(artifact.split("/")))
            )
        elif boundary == "article-input":
            valid_artifact = (
                isinstance(artifact, str)
                and bool(re.fullmatch(r"[^/]+/[^/.]+\.[A-Za-z0-9-]+", artifact))
                and "\\" not in artifact
                and not ({".", ".."} & set(artifact.split("/")))
            )
        else:
            valid_artifact = False
        if not valid_artifact:
            raise ValueError(f"invalid {boundary} artifact identity: {artifact!r}")
        keys.append((boundary, artifact))
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError(
            "freshness manifest groups must be unique and sorted by boundary, artifact"
        )
    return deduplicate_reason_groups(groups, reason_codes)


def deployment_freshness_result(
    *,
    site_commit: str | None,
    content_commit: str | None,
    meta_commit: str | None = None,
    meta_input_hashes: dict[str, str] | None = None,
    local_hashes: dict[str, str],
    remote_hashes: dict[str, str] | None,
    dead_links: dict[str, set[str]],
    stripped_links: dict[str, int],
    dropped_redirects: list[str],
    live_samples: dict[str, bool] | None,
    inherited_groups: Iterable[dict] = (),
    inherited_source: dict[str, str] | None = None,
    build_failed: bool = False,
    failure: dict[str, str] | None = None,
    reason_codes: dict[str, set[str]] | None = None,
) -> dict:
    """Construct a deterministic result from already observed deployment state."""
    remote_observed = remote_hashes is not None
    remote_hashes = remote_hashes or {}
    local_paths = set(local_hashes)
    remote_paths = set(remote_hashes)
    new_paths = sorted(local_paths - remote_paths) if remote_observed else []
    changed_paths = (
        sorted(
            path
            for path in local_paths & remote_paths
            if local_hashes[path] != remote_hashes[path]
        )
        if remote_observed
        else []
    )
    remote_only_paths = sorted(remote_paths - local_paths) if remote_observed else []
    live_mismatches = sorted(
        path for path, matches in (live_samples or {}).items() if not matches
    )
    inherited = deduplicate_reason_groups(inherited_groups, reason_codes)

    reasons_by_path: dict[str, set[str]] = {}

    def add_reasons(paths, reason: str) -> None:
        for path in paths:
            reasons_by_path.setdefault(path, set()).add(reason)

    add_reasons(new_paths, "path_changed")
    add_reasons(changed_paths, "path_changed")
    add_reasons(remote_only_paths, "remote_only")
    add_reasons(dead_links, "dead_link")
    add_reasons(stripped_links, "stripped_link")
    add_reasons(dropped_redirects, "redirect_dropped")
    add_reasons(live_mismatches, "live_hash_mismatch")
    if build_failed:
        add_reasons(["production-build"], "build_failed")

    repair_reasons = {
        "build_failed",
        "dead_link",
        "redirect_dropped",
        "live_hash_mismatch",
    }
    findings = []
    for path, reasons in sorted(reasons_by_path.items()):
        findings.append(
            {
                "boundary": "deployment",
                "artifact": path,
                "local_status": "invalid" if "build_failed" in reasons else "stale",
                "local_reasons": sorted(reasons),
                "inherited": [],
                "consequence": ("repair" if reasons & repair_reasons else "finish"),
            }
        )

    return {
        "boundary": "deployment",
        "site_commit": site_commit,
        "content_commit": content_commit,
        "meta_commit": meta_commit,
        "meta_input_hashes": dict(sorted((meta_input_hashes or {}).items())),
        "local_status": (
            "invalid"
            if build_failed
            else "unknown"
            if failure and (not findings or not remote_observed)
            else "current"
            if not findings
            else "stale"
        ),
        "inherited": inherited,
        "inherited_source": inherited_source,
        "failure": failure,
        "metrics": {
            "local_paths": len(local_paths),
            "remote_paths": len(remote_paths) if remote_observed else None,
            "remote_observed": remote_observed,
            "local_new": {"count": len(new_paths), "paths": new_paths},
            "local_changed": {"count": len(changed_paths), "paths": changed_paths},
            "remote_only": {
                "count": len(remote_only_paths) if remote_observed else None,
                "paths": remote_only_paths,
            },
            "dead_links": {
                "target_count": len(dead_links),
                "occurrence_count": sum(
                    len(sources) for sources in dead_links.values()
                ),
                "targets": sorted(dead_links),
            },
            "stripped_links": {
                "target_count": len(stripped_links),
                "occurrence_count": sum(stripped_links.values()),
                "targets": dict(sorted(stripped_links.items())),
            },
            "dropped_redirects": {
                "count": len(dropped_redirects),
                "paths": sorted(dropped_redirects),
            },
            "live_bytes": {
                "status": "not_sampled" if live_samples is None else "sampled",
                "sample_count": len(live_samples or {}),
                "mismatch_count": len(live_mismatches),
                "mismatch_paths": live_mismatches,
            },
        },
        "findings": findings,
    }
