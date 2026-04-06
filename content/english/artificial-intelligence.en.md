---
title: "AI Transparency"
description: "How Anomalica uses artificial intelligence, what it does, and what it does not do."
---

## Principle

AI is a tool in the pipeline, not the author. Every factual claim on this platform originates from a human-created source document. AI extracts, arranges, and verifies - it does not generate.

## Where AI is used

| Stage | What AI does | What AI does not do |
|-------|-------------|-------------------|
| Ingestion | Speech-to-text, text extraction from documents | Generate or infer content |
| Digestion | Identify claims, entities, and relationships | Draw on training data for facts |
| Assembly | Arrange extracted claims into readable articles | Editorially judge claim strength |
| Verification | Check assembled text against source graph | Approve or reject content |

## Independence

The AI model used for assembly and the model used for verification are from different providers in different jurisdictions. This ensures no single provider's biases can pass through both stages unchecked.

## Auditability

Each assembly step produces a cryptographic hash of its inputs and outputs. The prompt templates, knowledge graph state, and generated text are all recorded, making the process reproducible and auditable.

## What this means in practice

If an article on this site states that a specific person said a specific thing at a specific time, that statement traces to a source document where that person is recorded saying it. The AI did not infer, paraphrase, or hallucinate the claim. The source document is cited and the relevant passage is identified.
