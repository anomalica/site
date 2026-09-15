import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import deploy
from scripts.deployment_freshness import (
    FRESHNESS_ARCHITECTURE,
    deployment_freshness_result,
    inherited_groups_from_manifest,
    reason_code_contract,
)


def emitted_result(stdout: str) -> dict:
    _, payload = stdout.split("Deployment freshness result\n", 1)
    return json.loads(payload)


def upstream_manifest(groups: list[dict]) -> dict:
    return {
        "schema": "anomalica-freshness/v1",
        "generated_at": "2026-09-14T00:00:00Z",
        "source_queue_sha256": "b" * 64,
        "groups": groups,
    }


class DeploymentFreshnessResultTests(unittest.TestCase):
    def test_current_result_preserves_exact_commits_and_denominators(self):
        result = deployment_freshness_result(
            site_commit="a" * 40,
            content_commit="b" * 40,
            local_hashes={"en/index.html": "same"},
            remote_hashes={"en/index.html": "same"},
            dead_links={},
            stripped_links={},
            dropped_redirects=[],
            live_samples={"/en/": True},
        )

        self.assertEqual(result["site_commit"], "a" * 40)
        self.assertEqual(result["content_commit"], "b" * 40)
        self.assertIsNone(result["meta_commit"])
        self.assertEqual(result["meta_input_hashes"], {})
        self.assertEqual(result["local_status"], "current")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["metrics"]["local_paths"], 1)
        self.assertEqual(result["metrics"]["remote_paths"], 1)
        self.assertEqual(
            result["metrics"]["live_bytes"],
            {
                "status": "sampled",
                "sample_count": 1,
                "mismatch_count": 0,
                "mismatch_paths": [],
            },
        )

    def test_classifies_path_and_validation_drift_without_a_percentage(self):
        result = deployment_freshness_result(
            site_commit="site-commit",
            content_commit="content-commit",
            local_hashes={
                "new.txt": "new-hash",
                "changed.txt": "new-changed-hash",
                "same.txt": "same-hash",
            },
            remote_hashes={
                "changed.txt": "old-changed-hash",
                "same.txt": "same-hash",
                "old.txt": "old-hash",
            },
            dead_links={"/missing/": {"en/index.html", "en/about/index.html"}},
            stripped_links={"/unbuilt/": 3},
            dropped_redirects=["/former/"],
            live_samples={"/en/": True, "/en/about/": False},
        )

        metrics = result["metrics"]
        self.assertEqual(metrics["local_new"], {"count": 1, "paths": ["new.txt"]})
        self.assertEqual(
            metrics["local_changed"],
            {"count": 1, "paths": ["changed.txt"]},
        )
        self.assertEqual(metrics["remote_only"], {"count": 1, "paths": ["old.txt"]})
        self.assertEqual(metrics["dead_links"]["occurrence_count"], 2)
        self.assertEqual(metrics["stripped_links"]["occurrence_count"], 3)
        self.assertEqual(metrics["dropped_redirects"]["paths"], ["/former/"])
        self.assertEqual(metrics["live_bytes"]["mismatch_paths"], ["/en/about/"])
        self.assertNotIn("percentage", repr(result).lower())

        findings = {finding["artifact"]: finding for finding in result["findings"]}
        self.assertEqual(findings["new.txt"]["local_reasons"], ["path_changed"])
        self.assertEqual(findings["changed.txt"]["local_reasons"], ["path_changed"])
        self.assertEqual(findings["old.txt"]["local_reasons"], ["remote_only"])
        self.assertEqual(findings["/unbuilt/"]["local_reasons"], ["stripped_link"])
        self.assertEqual(findings["/former/"]["consequence"], "repair")
        self.assertEqual(findings["/en/about/"]["consequence"], "repair")

    def test_not_sampled_is_distinct_from_a_zero_mismatch_sample(self):
        result = deployment_freshness_result(
            site_commit="site",
            content_commit="content",
            local_hashes={},
            remote_hashes={},
            dead_links={},
            stripped_links={},
            dropped_redirects=[],
            live_samples=None,
        )

        self.assertEqual(result["metrics"]["live_bytes"]["status"], "not_sampled")
        self.assertEqual(result["metrics"]["live_bytes"]["sample_count"], 0)

    def test_unobserved_remote_state_is_unknown_not_an_empty_zone(self):
        result = deployment_freshness_result(
            site_commit="site",
            content_commit="content",
            local_hashes={"en/index.html": "hash"},
            remote_hashes=None,
            dead_links={},
            stripped_links={},
            dropped_redirects=[],
            live_samples=None,
            failure={"stage": "publish", "type": "OSError", "message": "lost"},
        )

        self.assertEqual(result["local_status"], "unknown")
        self.assertFalse(result["metrics"]["remote_observed"])
        self.assertIsNone(result["metrics"]["remote_paths"])
        self.assertEqual(result["metrics"]["local_new"]["count"], 0)
        self.assertIsNone(result["metrics"]["remote_only"]["count"])

    def test_build_failure_and_inherited_groups_are_canonical(self):
        inherited = [
            {
                "boundary": "digest-generation",
                "artifact": "digest.yaml",
                "local_status": "unknown",
                "local_reasons": ["generation_unknown"],
                "inherited": [],
                "consequence": "finish",
            },
            {
                "boundary": "digest-generation",
                "artifact": "digest.yaml",
                "local_status": "stale",
                "local_reasons": ["generation_behind"],
                "inherited": [],
                "consequence": "repair",
            },
        ]
        result = deployment_freshness_result(
            site_commit="site",
            content_commit=None,
            local_hashes={},
            remote_hashes={},
            dead_links={},
            stripped_links={},
            dropped_redirects=[],
            live_samples=None,
            inherited_groups=inherited,
            inherited_source={"path": "/input.json", "sha256": "1" * 64},
            build_failed=True,
            failure={"stage": "build", "type": "DeployError", "message": "bad"},
        )

        self.assertEqual(result["local_status"], "invalid")
        self.assertEqual(result["findings"][0]["local_reasons"], ["build_failed"])
        self.assertEqual(len(result["inherited"]), 1)
        self.assertEqual(
            result["inherited"][0]["local_reasons"],
            ["generation_behind", "generation_unknown"],
        )
        self.assertEqual(result["inherited"][0]["local_status"], "stale")
        self.assertEqual(result["inherited"][0]["consequence"], "repair")
        self.assertEqual(result["findings"][0]["inherited"], [])
        self.assertEqual(result["inherited_source"]["sha256"], "1" * 64)

    def test_manifest_rejects_nested_groups_instead_of_flattening_them(self):
        group = {
            "boundary": "article-input",
            "artifact": "people/example.en",
            "local_status": "stale",
            "local_reasons": ["brief_hash_mismatch"],
            "inherited": [
                {
                    "boundary": "digest-input",
                    "artifact": "sha256:" + "a" * 64,
                    "local_status": "stale",
                    "local_reasons": ["pre_digest_hash_mismatch"],
                    "inherited": [],
                    "consequence": "finish",
                }
            ],
            "consequence": "finish",
        }
        with self.assertRaisesRegex(ValueError, "inherited must be exactly \\[\\]"):
            inherited_groups_from_manifest(upstream_manifest([group, group]))

    def test_manifest_rejects_unknown_top_level_field(self):
        manifest = upstream_manifest([])
        manifest["future"] = True

        with self.assertRaisesRegex(ValueError, "unknown: future"):
            inherited_groups_from_manifest(manifest)

    def test_manifest_rejects_unknown_group_field(self):
        group = {
            "boundary": "brief-selection",
            "artifact": "people/example.en",
            "local_status": "stale",
            "local_reasons": ["payload_hash_mismatch"],
            "inherited": [],
            "consequence": "finish",
            "future": True,
        }

        with self.assertRaisesRegex(ValueError, "unknown: future"):
            inherited_groups_from_manifest(upstream_manifest([group]))

    def test_manifest_rejects_missing_group_field(self):
        group = {
            "boundary": "brief-selection",
            "artifact": "people/example.en",
            "local_status": "stale",
            "local_reasons": ["payload_hash_mismatch"],
            "inherited": [],
        }

        with self.assertRaisesRegex(ValueError, "missing: consequence"):
            inherited_groups_from_manifest(upstream_manifest([group]))

    def test_manifest_rejects_noncanonical_upstream_reason(self):
        with self.assertRaisesRegex(ValueError, "invalid article-input reason"):
            inherited_groups_from_manifest(
                upstream_manifest(
                    [
                        {
                            "boundary": "article-input",
                            "artifact": "people/example.en",
                            "local_status": "stale",
                            "local_reasons": ["made_up"],
                            "inherited": [],
                            "consequence": "finish",
                        }
                    ]
                )
            )

    def test_manifest_rejects_noncanonical_order_duplicates_and_artifacts(self):
        def group(boundary, artifact, reason):
            return {
                "boundary": boundary,
                "artifact": artifact,
                "local_status": "stale",
                "local_reasons": [reason],
                "inherited": [],
                "consequence": "finish",
            }

        digest = group("digest-input", "sha256:" + "a" * 64, "pre_digest_hash_mismatch")
        article = group("article-input", "people/example.en", "payload_hash_mismatch")
        with self.assertRaisesRegex(ValueError, "unique and sorted"):
            inherited_groups_from_manifest(upstream_manifest([digest, article]))
        with self.assertRaisesRegex(ValueError, "unique and sorted"):
            inherited_groups_from_manifest(upstream_manifest([article, article]))

        article["artifact"] = "people/example.md.en"
        with self.assertRaisesRegex(ValueError, "artifact identity"):
            inherited_groups_from_manifest(upstream_manifest([article]))

        article["artifact"] = "../example.en"
        with self.assertRaisesRegex(ValueError, "artifact identity"):
            inherited_groups_from_manifest(upstream_manifest([article]))

        article["artifact"] = "people/example.en"
        article["local_status"] = "current"
        with self.assertRaisesRegex(ValueError, "current status"):
            inherited_groups_from_manifest(upstream_manifest([article]))

        digest["artifact"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "artifact identity"):
            inherited_groups_from_manifest(upstream_manifest([digest]))

    def test_reason_placements_come_from_current_canonical_architecture(self):
        contract = reason_code_contract(FRESHNESS_ARCHITECTURE.read_text())

        self.assertIn("payload_hash_mismatch", contract["brief-selection"])
        self.assertIn("payload_hash_mismatch", contract["article-input"])
        self.assertNotIn("payload_hash_mismatch", contract["digest-input"])

        misplaced = upstream_manifest(
            [
                {
                    "boundary": "digest-input",
                    "artifact": "sha256:" + "a" * 64,
                    "local_status": "stale",
                    "local_reasons": ["payload_hash_mismatch"],
                    "inherited": [],
                    "consequence": "finish",
                }
            ]
        )
        with self.assertRaisesRegex(ValueError, "invalid digest-input reason"):
            inherited_groups_from_manifest(misplaced)

    def test_guarded_assimilator_manifest_reaches_deployment_findings(self):
        fixture = Path(__file__).parent / "fixtures" / "assimilator-freshness-v1.json"
        assimilator_workspace = (
            Path(__file__).resolve().parents[2] / "assimilator/workspace"
        )
        with mock.patch.object(sys, "path", [str(assimilator_workspace), *sys.path]):
            from assimilator.scheduler import freshness_manifest

        brief_group = {
            "boundary": "brief-selection",
            "artifact": "people/example-person",
            "local_status": "stale",
            "local_reasons": ["payload_hash_mismatch"],
            "inherited": [
                {
                    "boundary": "graph-import",
                    "artifact": "sha256:" + "a" * 64,
                    "local_status": "stale",
                    "local_reasons": ["digest_hash_mismatch"],
                    "inherited": [],
                    "consequence": "finish",
                }
            ],
            "consequence": "finish",
        }
        produced = freshness_manifest(
            {
                "generatedAt": "2026-09-14T00:00:00Z",
                "jobs": [
                    {
                        "local_reason_groups": [brief_group],
                        "inherited_reason_groups": [],
                    }
                ],
            },
            "b" * 64,
        )
        self.assertEqual(json.loads(fixture.read_text()), produced)

        expected = hashlib.sha256(fixture.read_bytes()).hexdigest()
        inherited = deploy.guarded_inherited_groups(fixture, expected)
        result = deployment_freshness_result(
            site_commit="site",
            content_commit="content",
            local_hashes={"en/index.html": "new"},
            remote_hashes={"en/index.html": "old"},
            dead_links={},
            stripped_links={},
            dropped_redirects=[],
            live_samples=None,
            inherited_groups=inherited,
            inherited_source={"path": str(fixture), "sha256": expected},
        )

        inherited_by_boundary = {
            group["boundary"]: group for group in result["inherited"]
        }
        self.assertEqual(
            inherited_by_boundary["brief-selection"]["local_reasons"],
            ["payload_hash_mismatch"],
        )
        self.assertEqual(
            inherited_by_boundary["graph-import"]["local_reasons"],
            ["digest_hash_mismatch"],
        )
        self.assertEqual(result["inherited_source"]["sha256"], expected)

    def test_guarded_manifest_rejects_bytes_other_than_the_authorised_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "freshness.json"
            path.write_text(json.dumps(upstream_manifest([])))
            with self.assertRaisesRegex(deploy.DeployError, "SHA-256 mismatch"):
                deploy.guarded_inherited_groups(path, "0" * 64)

            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(deploy.guarded_inherited_groups(path, expected), [])

    def test_guarded_manifest_rejects_duplicate_json_members(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "freshness.json"
            path.write_text(
                '{"schema":"anomalica-freshness/v1",'
                '"schema":"anomalica-freshness/v1",'
                '"generated_at":"now","source_queue_sha256":"'
                + "a" * 64
                + '","groups":[]}'
            )
            expected = hashlib.sha256(path.read_bytes()).hexdigest()

            with self.assertRaisesRegex(deploy.DeployError, "duplicate JSON"):
                deploy.guarded_inherited_groups(path, expected)


class MetaInputTests(unittest.TestCase):
    def create_meta_repository(self, root: Path, omit: str | None = None):
        repository = root / "meta-repository"
        repository.mkdir()
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        for index, relative in enumerate(deploy.META_INPUTS):
            if relative == omit:
                continue
            path = repository / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"input-{index}".encode())
        subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        return repository, deploy.repository_commit(repository)

    def test_repository_snapshot_uses_committed_bytes_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            tracked = repository / "tracked.txt"
            tracked.write_text("committed")
            subprocess.run(
                ["git", "-C", str(repository), "add", "tracked.txt"], check=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            revision = deploy.repository_commit(repository)
            committed = tracked.read_text()
            tracked.write_text("uncommitted")
            (repository / "untracked.txt").write_text("untracked")

            snapshot = deploy.snapshot_repository(
                repository, root / "snapshot", revision
            )

            self.assertEqual((snapshot / "tracked.txt").read_text(), committed)
            self.assertFalse((snapshot / "untracked.txt").exists())

    def test_changed_meta_input_fails_closed_but_unrelated_untracked_file_does_not(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, revision = self.create_meta_repository(root)
            (repository / "AGENTS.md").write_text("unrelated")
            destination = root / "clean-snapshot"
            with mock.patch.object(deploy, "META_REPO", repository):
                deploy.committed_meta_inputs(destination, revision)

                (repository / deploy.META_INPUTS[0]).write_text("changed")
                with self.assertRaisesRegex(deploy.DeployError, "differs from"):
                    deploy.committed_meta_inputs(root / "dirty-snapshot", revision)

    def test_meta_snapshot_requires_and_hashes_every_mounted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, revision = self.create_meta_repository(root)
            destination = root / "meta"
            with mock.patch.object(deploy, "META_REPO", repository):
                hashes = deploy.committed_meta_inputs(destination, revision)

            self.assertEqual(set(hashes), set(deploy.META_INPUTS))
            self.assertEqual(
                hashes[deploy.META_INPUTS[0]],
                hashlib.sha256(
                    (repository / deploy.META_INPUTS[0]).read_bytes()
                ).hexdigest(),
            )

            missing_root = root / "missing"
            missing_root.mkdir()
            missing_repository, missing_revision = self.create_meta_repository(
                missing_root, omit=deploy.META_INPUTS[-1]
            )
            with mock.patch.object(deploy, "META_REPO", missing_repository):
                with self.assertRaisesRegex(deploy.DeployError, "input is missing"):
                    deploy.committed_meta_inputs(
                        root / "missing-snapshot", missing_revision
                    )

    def test_module_override_rejects_unbound_meta_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            site.mkdir()
            mounts = "\n".join(
                f'[[module.mounts]]\nsource = "../anomalica/{relative}"\ntarget = "data/{index}"'
                for index, relative in enumerate(
                    [*deploy.MOUNTED_META_INPUTS, "reference/extra.yaml"]
                )
            )
            (site / "hugo.toml").write_text(mounts)

            with self.assertRaisesRegex(deploy.DeployError, "hash-bound input set"):
                deploy.module_override(
                    site,
                    root / "content",
                    root / "meta",
                    root / "mounts.toml",
                )

    def test_recorded_retirement_is_not_a_dropped_redirect_finding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            redirects = root / "redirects.yaml"
            redirects.write_text("redirects:\n  - from: /en/retired/\n    gone: true\n")
            with mock.patch.object(
                deploy,
                "read_state",
                return_value={"aliases": ["/en/retired/", "/en/lost/"]},
            ):
                dropped = deploy.report_alias_changes(
                    root / "build", persist=False, redirects=redirects
                )

            self.assertEqual(dropped, ["/en/lost/"])


class DeploymentFailureEmissionTests(unittest.TestCase):
    def run_main(self, arguments: list[str], patches: list[mock._patch]):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(sys, "argv", ["deploy.py", *arguments])
            )
            for patch in patches:
                stack.enter_context(patch)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = deploy.main()
        return code, emitted_result(stdout.getvalue()), stderr.getvalue()

    def test_build_failure_emits_result_then_preserves_original_error(self):
        error = deploy.DeployError("diagram failed")
        code, result, stderr = self.run_main(
            ["--dry-run"],
            [
                mock.patch.object(
                    deploy,
                    "repository_commit",
                    side_effect=["site", "content", "meta"],
                ),
                mock.patch.object(
                    deploy, "snapshot_repository", return_value=Path("/snapshot/site")
                ),
                mock.patch.object(
                    deploy,
                    "committed_meta_inputs",
                    return_value={"reference/format-specs.yaml": "hash"},
                ),
                mock.patch.object(deploy, "committed_reason_codes", return_value={}),
                mock.patch.object(deploy, "check_diagram_current", side_effect=error),
            ],
        )

        self.assertEqual(code, 1)
        self.assertEqual(result["site_commit"], "site")
        self.assertEqual(result["content_commit"], "content")
        self.assertEqual(result["findings"][0]["local_reasons"], ["build_failed"])
        self.assertIn("deploy failed: diagram failed", stderr)

    def test_commit_failure_still_reports_the_other_obtainable_commit(self):
        commit_error = OSError("site revision unavailable")
        code, result, stderr = self.run_main(
            ["--dry-run"],
            [
                mock.patch.object(
                    deploy,
                    "repository_commit",
                    side_effect=[commit_error, "content", "meta"],
                )
            ],
        )

        self.assertEqual(code, 1)
        self.assertIsNone(result["site_commit"])
        self.assertEqual(result["content_commit"], "content")
        self.assertEqual(result["local_status"], "unknown")
        self.assertIn("deploy failed: site revision unavailable", stderr)

    def test_dead_link_refusal_emits_paths_before_original_error(self):
        secret = mock.patch.object(deploy, "secret")
        code, result, stderr = self.run_main(
            ["--dry-run"],
            [
                mock.patch.object(
                    deploy,
                    "repository_commit",
                    side_effect=["site", "content", "meta"],
                ),
                mock.patch.object(
                    deploy, "snapshot_repository", return_value=Path("/snapshot/site")
                ),
                mock.patch.object(
                    deploy,
                    "committed_meta_inputs",
                    return_value={"reference/format-specs.yaml": "hash"},
                ),
                mock.patch.object(deploy, "committed_reason_codes", return_value={}),
                mock.patch.object(deploy, "check_diagram_current"),
                mock.patch.object(
                    deploy,
                    "snapshot_content",
                    return_value=(Path("/snapshot"), "content"),
                ),
                mock.patch.object(deploy, "build"),
                mock.patch.object(deploy, "apply_redirects"),
                mock.patch.object(deploy, "verify_assets_fingerprinted"),
                mock.patch.object(
                    deploy,
                    "verify_no_dead_links",
                    return_value={"/missing/": {"en/index.html"}},
                ),
                secret,
            ],
        )

        self.assertEqual(code, 1)
        self.assertEqual(result["findings"][0]["artifact"], "/missing/")
        self.assertEqual(result["findings"][0]["local_reasons"], ["dead_link"])
        self.assertIn("deploy failed: 1 dead internal link target", stderr)

    def test_successful_publish_uses_post_publish_remote_map_and_is_current(self):
        write_state = mock.Mock()
        code, result, stderr = self.run_main(
            [],
            [
                mock.patch.object(
                    deploy,
                    "repository_commit",
                    side_effect=["site", "content", "meta"],
                ),
                mock.patch.object(
                    deploy, "snapshot_repository", return_value=Path("/snapshot/site")
                ),
                mock.patch.object(
                    deploy,
                    "committed_meta_inputs",
                    return_value={"reference/format-specs.yaml": "meta-hash"},
                ),
                mock.patch.object(deploy, "committed_reason_codes", return_value={}),
                mock.patch.object(deploy, "check_diagram_current"),
                mock.patch.object(
                    deploy,
                    "snapshot_content",
                    return_value=(Path("/snapshot/content"), "content"),
                ),
                mock.patch.object(deploy, "build"),
                mock.patch.object(deploy, "apply_redirects"),
                mock.patch.object(deploy, "verify_assets_fingerprinted"),
                mock.patch.object(deploy, "verify_no_dead_links", return_value={}),
                mock.patch.object(deploy, "report_unresolved_links", return_value={}),
                mock.patch.object(deploy, "report_alias_changes", return_value=[]),
                mock.patch.object(deploy, "secret", return_value="secret"),
                mock.patch.object(
                    deploy,
                    "local_files",
                    return_value={"en/index.html": (Path("/built/index.html"), "new")},
                ),
                mock.patch.object(
                    deploy,
                    "remote_files",
                    side_effect=[
                        {"en/index.html": "old"},
                        {"en/index.html": "new"},
                    ],
                ),
                mock.patch.object(deploy, "check_resurrected"),
                mock.patch.object(deploy, "check_removals"),
                mock.patch.object(deploy, "in_parallel"),
                mock.patch.object(deploy, "purge"),
                mock.patch.object(deploy, "verify_live", return_value={"/en/": True}),
                mock.patch.object(deploy, "built_aliases", return_value=[]),
                mock.patch.object(deploy, "write_state", write_state),
            ],
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(result["local_status"], "current")
        self.assertEqual(result["meta_commit"], "meta")
        self.assertEqual(
            result["meta_input_hashes"],
            {"reference/format-specs.yaml": "meta-hash"},
        )
        self.assertEqual(result["metrics"]["local_changed"]["count"], 0)
        self.assertEqual(write_state.call_count, 2)

    def test_live_hash_refusal_emits_mismatch_before_original_error(self):
        code, result, stderr = self.run_main(
            [],
            [
                mock.patch.object(
                    deploy,
                    "repository_commit",
                    side_effect=["site", "content", "meta"],
                ),
                mock.patch.object(
                    deploy, "snapshot_repository", return_value=Path("/snapshot/site")
                ),
                mock.patch.object(
                    deploy,
                    "committed_meta_inputs",
                    return_value={"reference/format-specs.yaml": "hash"},
                ),
                mock.patch.object(deploy, "committed_reason_codes", return_value={}),
                mock.patch.object(deploy, "check_diagram_current"),
                mock.patch.object(
                    deploy,
                    "snapshot_content",
                    return_value=(Path("/snapshot"), "content"),
                ),
                mock.patch.object(deploy, "build"),
                mock.patch.object(deploy, "apply_redirects"),
                mock.patch.object(deploy, "verify_assets_fingerprinted"),
                mock.patch.object(deploy, "verify_no_dead_links", return_value={}),
                mock.patch.object(deploy, "report_unresolved_links", return_value={}),
                mock.patch.object(deploy, "report_alias_changes", return_value=[]),
                mock.patch.object(deploy, "secret", return_value="secret"),
                mock.patch.object(
                    deploy,
                    "local_files",
                    return_value={"en/index.html": (Path("/built/index.html"), "new")},
                ),
                mock.patch.object(
                    deploy,
                    "remote_files",
                    side_effect=[
                        {"en/index.html": "old"},
                        {"en/index.html": "new"},
                        {"en/index.html": "new"},
                    ],
                ),
                mock.patch.object(deploy, "check_resurrected"),
                mock.patch.object(deploy, "check_removals"),
                mock.patch.object(deploy, "in_parallel"),
                mock.patch.object(deploy, "purge"),
                mock.patch.object(deploy, "verify_live", return_value={"/en/": False}),
            ],
        )

        self.assertEqual(code, 1)
        findings = {finding["artifact"]: finding for finding in result["findings"]}
        self.assertEqual(findings["/en/"]["local_reasons"], ["live_hash_mismatch"])
        self.assertEqual(result["metrics"]["live_bytes"]["mismatch_count"], 1)
        self.assertIn("deploy failed: https://anomalica.is/en/ answers", stderr)

    def test_live_http_failure_is_retained_as_a_sample(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(deploy.urllib.request, "urlopen", side_effect=OSError()),
        ):
            page = Path(directory) / "en/index.html"
            page.parent.mkdir(parents=True)
            page.write_text("built")

            samples = deploy.verify_live(Path(directory), ["/en/"], attempts=1)

        self.assertEqual(samples, {"/en/": False})


if __name__ == "__main__":
    unittest.main()
