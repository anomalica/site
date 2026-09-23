---
schema: anomalica/public-record/2
content_kind: record
title: Enriched fixture
description: A generated explanation used to test the enriched Record page.
record_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
aliases:
  - /records/enriched-fixture/
metadata:
  source_types: [video]
  document_type: testimony
  publisher: Fixture Publisher
  creators: [Alex Example]
  published_date: "2026-09-02"
  duration: 125
source:
  assets:
    - ordinal: 1
      source_type: video
      file_format: mp4
      acquired_at: "2026-09-03T12:34:56+09:00"
      selected_record_pages: [1]
      capabilities:
        source_body:
          mode: display
          reason: allowed
          resource: /public/enriched-source.html
        archived_original:
          mode: public
          reason: allowed
          url: /public/enriched-original.mp4
        media:
          mode: display
          reason: allowed
          items:
            - url: /public/enriched-still.svg
              media_type: image/svg+xml
        provider_embed:
          mode: embed
          reason: allowed
          url: https://www.youtube.com/watch?v=Fixture123
        external_link:
          mode: link
          reason: allowed
          url: https://example.org/source?id=fixture
references:
  - text: The fixture supports its first test claim.
    source: Fixture Publisher
    location: Asset 1, page 1
    quote: This is the supporting fixture passage.
    source_anchor_id: 11111111111111111111111111111111
    inspection_url: /records/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb#source-11111111111111111111111111111111
  - text: A second claim intentionally uses the same evidence site.
    source: Fixture Publisher
    location: Asset 1, page 1
    quote: This is the same supporting fixture passage.
    source_anchor_id: 11111111111111111111111111111111
built_by:
  model: fixture-model
---

## Fixture explanation

ENRICHED_EXPLANATION_RENDERED.<sup>1</sup>
