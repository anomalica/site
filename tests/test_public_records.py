import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONFIG = "tests/fixtures/public-records/hugo.toml"

SHELL_HASH = "a" * 56
ENRICHED_HASH = "b" * 56
MULTI_ASSET_HASH = "c" * 56
LEGACY_SCALAR_HASH = "d" * 56


class PublicRecordTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary_directory.cleanup)
        cls.output = Path(cls._temporary_directory.name)
        subprocess.run(
            [
                "hugo",
                "--config",
                FIXTURE_CONFIG,
                "--destination",
                str(cls.output),
                "--cleanDestinationDir",
            ],
            cwd=SITE_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def rendered_record(cls, record_hash: str) -> str:
        return (cls.output / "en" / "records" / record_hash / "index.html").read_text()

    def test_metadata_shell_is_canonical_noindex_and_contains_no_enrichment(self):
        html = self.rendered_record(SHELL_HASH)

        self.assertIn('<meta name="robots" content="noindex">', html)
        self.assertIn(
            f'<link rel="canonical" href="https://fixture.invalid/en/records/{SHELL_HASH}/">',
            html,
        )
        self.assertIn("Metadata shell fixture", html)
        self.assertIn("Fixture Archive", html)
        self.assertIn("A reviewed public account is not available", html)
        self.assertNotIn("SHELL_GENERATED_DESCRIPTION_MUST_NOT_RENDER", html)
        self.assertNotIn("SHELL_BODY_MUST_NOT_RENDER", html)
        self.assertNotIn("/private/shell-source.pdf", html)
        self.assertNotIn("SHELL_SOURCE_BODY_MUST_NOT_RENDER", html)
        self.assertNotIn("SHELL_EXTERNAL_LINK_MUST_NOT_RENDER", html)
        self.assertNotIn("SHELL_CLAIM_MUST_NOT_RENDER", html)
        self.assertNotIn("SHELL_QUOTE_MUST_NOT_RENDER", html)

    def test_enriched_page_renders_evidence_and_five_independent_capabilities(self):
        html = self.rendered_record(ENRICHED_HASH)

        self.assertNotIn('name="robots"', html)
        self.assertIn(
            f'<link rel="canonical" href="https://fixture.invalid/en/records/{ENRICHED_HASH}/">',
            html,
        )
        self.assertIn("ENRICHED_EXPLANATION_RENDERED", html)
        self.assertIn("/public/enriched-source.html", html)
        self.assertIn("/public/enriched-original.mp4", html)
        self.assertIn("/public/enriched-still.svg", html)
        self.assertIn("youtube-nocookie.com/embed/Fixture123", html)
        self.assertIn("https://example.org/source?id=fixture", html)
        self.assertIn("2026-09-03T12:34:56", html)
        self.assertEqual(html.count('id="source-11111111111111111111111111111111"'), 1)
        for label in (
            "Source text",
            "Archived copy",
            "Media",
            "Provider player",
            "Original source",
        ):
            self.assertIn(label, html)

    def test_entity_claim_links_to_stable_record_evidence_site(self):
        html = (
            self.output / "en" / "people" / "evidence-link" / "index.html"
        ).read_text()

        self.assertIn(
            f'href="/en/records/{ENRICHED_HASH}/#source-11111111111111111111111111111111"',
            html,
        )
        self.assertIn("View the source record", html)

    def test_multi_asset_panels_preserve_order_and_do_not_widen_permissions(self):
        html = self.rendered_record(MULTI_ASSET_HASH)

        self.assertEqual(html.count('aria-labelledby="source-asset-'), 2)
        self.assertLess(html.index("Source 1"), html.index("Source 2"))
        self.assertIn("Selected record pages 1, 3", html)
        self.assertIn("Selected record page 2", html)
        self.assertIn("2026-02-28T23:59:59Z", html)
        self.assertNotIn("2026-02-31T12:00:00Z", html)
        self.assertIn("/public/asset-one-body.html", html)
        self.assertNotIn("GATED_BODY_MUST_NOT_RENDER", html)
        self.assertNotIn("GATED_ARCHIVE_MUST_NOT_RENDER", html)
        self.assertNotIn("GATED_LOCATOR_MUST_NOT_RENDER", html)
        self.assertIn("/public/asset-one.pdf", html)
        self.assertIn("/public/asset-two.svg", html)
        self.assertIn("youtube-nocookie.com/embed/Fixture456", html)
        for label in (
            "Source text",
            "Archived copy",
            "Media",
            "Provider player",
            "Original source",
        ):
            self.assertEqual(html.count(f">{label}<"), 2)

    def test_legacy_scalar_cannot_widen_v2_access(self):
        html = self.rendered_record(LEGACY_SCALAR_HASH)

        self.assertIn('<meta name="robots" content="noindex">', html)
        self.assertIn("Safe metadata publisher", html)
        self.assertIn("A reviewed public account is not available", html)
        for forbidden in (
            "LEGACY_SCALAR_DESCRIPTION_MUST_NOT_RENDER",
            "LEGACY_SCALAR_LOCATOR_MUST_NOT_RENDER",
            "LEGACY_SCALAR_REFERENCE_MUST_NOT_RENDER",
            "LEGACY_SCALAR_QUOTE_MUST_NOT_RENDER",
            "LEGACY_SCALAR_BODY_MUST_NOT_RENDER",
            "/home/fixture/private.md",
            "sha256:" + "e" * 64,
        ):
            self.assertNotIn(forbidden, html)

    def test_legacy_v1_page_remains_concrete_during_migration(self):
        html = (
            self.output / "en" / "records" / "legacy-record" / "index.html"
        ).read_text()

        self.assertNotIn('name="robots"', html)
        self.assertIn("LEGACY_V1_BODY_REMAINS_RENDERED", html)
        self.assertIn("https://example.org/legacy", html)

        listing = (self.output / "en" / "records" / "index.html").read_text()
        self.assertIn("Legacy concrete fixture", listing)
        self.assertIn("Metadata shell fixture", listing)
        self.assertNotIn("SHELL_GENERATED_DESCRIPTION_MUST_NOT_RENDER", listing)

    def test_alias_search_and_rss_outputs_preserve_shell_boundary(self):
        alias = (
            self.output / "records" / "enriched-fixture" / "index.html"
        ).read_text()
        self.assertIn('<meta name="robots" content="noindex">', alias)
        self.assertIn(
            f'<link rel="canonical" href="https://fixture.invalid/en/records/{ENRICHED_HASH}/">',
            alias,
        )

        search_entries = json.loads((self.output / "en" / "index.json").read_text())
        by_title = {entry["t"]: entry for entry in search_entries}
        self.assertEqual(by_title["Metadata shell fixture"]["d"], "")
        self.assertEqual(by_title["Legacy scalar attack fixture"]["d"], "")
        self.assertIn(
            "existing public-record/1", by_title["Legacy concrete fixture"]["d"]
        )

        rss = (self.output / "en" / "records" / "index.xml").read_text()
        self.assertTrue(rss.startswith('<?xml version="1.0"'))
        self.assertIn("Metadata shell fixture", rss)
        self.assertNotIn("SHELL_BODY_MUST_NOT_RENDER", rss)
        self.assertNotIn("LEGACY_SCALAR_BODY_MUST_NOT_RENDER", rss)


if __name__ == "__main__":
    unittest.main()
