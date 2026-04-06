---
title: "Methodology"
description: "How content is produced, from source material to published article."
---

## Pipeline

Content moves through five stages:

1. **Ingestion** - source material (documents, transcripts, news articles) is converted into a standardised record format
2. **Digestion** - atomic claims are extracted from records and integrated into a knowledge graph with entities, relationships, and provenance chains
3. **Scoring** - evidence strength is computed algorithmically from attestation level (first-hand, second-hand, third-hand), corroboration across independent sources, and source type
4. **Assembly** - articles are generated per language from the knowledge graph, with each factual assertion traceable to its source
5. **Verification** - an independent AI model from a different provider verifies that assembled content accurately reflects the knowledge graph

## Claims as atomic units

The knowledge graph does not store articles. It stores individual claims, each linked to the source document, page, and speaker from which it was extracted. Articles are assembled from these claims, not written as monolithic text.

## AI involvement

AI is used for extraction (identifying claims and entities in documents), arrangement (assembling articles from graph data), and verification (checking assembly against sources). AI does not generate factual content from its training data. Every claim in the knowledge graph originates from a specific source document.

## Source types

Anomalica ingests publicly available material: government reports, congressional testimony, court documents, academic papers, news articles, podcast transcripts, and recorded interviews. Each source carries metadata about its type, provenance, and the attestation level of claims within it.

## Architecture decisions

The technical decisions behind this methodology are documented as Architecture Decision Records. See [Architecture Decisions](/decisions/) for the full record.
