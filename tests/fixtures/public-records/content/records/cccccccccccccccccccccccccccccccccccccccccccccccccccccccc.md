---
schema: anomalica/public-record/2
content_kind: record
title: Multi-Asset fixture
description: A composite Record assembled from two independently authorised Assets.
record_hash: cccccccccccccccccccccccccccccccccccccccccccccccccccccccc
metadata:
  source_types: [pdf, image]
  document_type: report
  publisher: Composite Archive
  pages: 3
source:
  assets:
    - ordinal: 1
      source_type: pdf
      file_format: pdf
      acquired_at: "2026-02-28T23:59:59Z"
      pages: 8
      selected_record_pages: [1, 3]
      capabilities:
        source_body:
          mode: display
          reason: allowed
          resource: /public/asset-one-body.html
        archived_original:
          mode: public
          reason: allowed
          url: /public/asset-one.pdf
        media:
          mode: none
          reason: unavailable
        provider_embed:
          mode: none
          reason: unsupported
        external_link:
          mode: link
          reason: allowed
          url: https://example.org/asset-one
    - ordinal: 2
      source_type: image
      file_format: png
      acquired_at: "2026-02-31T12:00:00Z"
      pages: 1
      selected_record_pages: [2]
      capabilities:
        source_body:
          mode: none
          reason: copyright
          resource: /private/GATED_BODY_MUST_NOT_RENDER.html
        archived_original:
          mode: none
          reason: copyright
          url: /private/GATED_ARCHIVE_MUST_NOT_RENDER.pdf
        media:
          mode: display
          reason: allowed
          items:
            - url: /public/asset-two.svg
              media_type: image/svg+xml
        provider_embed:
          mode: embed
          reason: allowed
          url: https://youtu.be/Fixture456
        external_link:
          mode: none
          reason: unavailable
          url: https://private.example/GATED_LOCATOR_MUST_NOT_RENDER
references: []
built_by:
  model: fixture-model
---

MULTI_ASSET_EXPLANATION_RENDERED.
