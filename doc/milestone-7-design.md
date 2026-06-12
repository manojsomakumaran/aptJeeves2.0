# Milestone 7 Design: Model-Backed Intelligence

## Goal

Milestone 7 replaces the remaining fake or placeholder model surfaces with production-shaped provider integrations while preserving the deterministic privacy and validation boundaries built in earlier milestones.

This milestone starts from the hardened milestone 6 pipeline and upgrades the intelligence layers, not the storage contract.

## Scope

```text
implement provider-backed extractor
implement optional LLM-backed intent classifier with deterministic fallback
wire CLI extraction to choose fake or provider extractor from config
validate provider-backed ask flow with mocked integration tests
record extractor and classifier versions in observability payloads
```

## Non-Goals

```text
human review queue UI
fine-tuned ranking models
multi-provider orchestration
streaming answer output
```

## Design

### 1. LLM Extractor

Add an `LLMExtractor` that implements the existing extractor protocol and returns the same validated JSON contract used by `ExtractionService`.

Requirements:

```text
accept sanitized MessageForExtraction inputs only
use JSON-only output prompts
reuse validate_extraction_payload before storage
fail closed on malformed or incomplete responses
```

The fake extractor remains available for tests and offline development.

### 2. Intent Classification

Add a provider-backed intent classifier that returns the existing `IntentResult` shape.

Strategy:

```text
if provider intent classification is enabled and API credentials exist, call the LLM classifier
if the provider call fails or returns an unsupported label, fall back to keyword_intent_v1
emit the classifier version in query observability payloads
```

### 3. Runtime Selection

Configuration additions:

```text
APTJEEVES_EXTRACTION_BACKEND=fake|openai
APTJEEVES_EXTRACTION_MODEL=gpt-4.1-mini
APTJEEVES_INTENT_BACKEND=keyword|openai
APTJEEVES_INTENT_MODEL=gpt-4.1-mini
```

CLI behavior:

```text
extract-pending uses the selected extraction backend
ask uses the selected intent backend and existing answerer selection
OpenAI embeddings and LLM answering from milestone 5 remain the provider-backed path
```

### 4. Testing

Required tests:

```text
LLMExtractor calls OpenAI with sanitized message inputs and returns validated facts
LLMExtractor failure marks messages failed and emits extraction_batch_failed
LLM intent classifier maps provider output into supported intent labels
ask falls back to keyword intent classification when provider classification fails
CLI extract-pending chooses the configured extractor backend
```

## Exit Criteria

Milestone 7 is complete when:

```text
the repo can run extraction with either fake or OpenAI-backed extractors
the repo can classify intent with either keyword or OpenAI-backed classifiers
provider-backed paths are covered by mocked tests and preserve privacy constraints
```