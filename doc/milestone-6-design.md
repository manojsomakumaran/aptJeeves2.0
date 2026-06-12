# Milestone 6 Design: Guardrails, Replay, And Hardening

## Goal

Milestone 6 hardens the ask pipeline so the system can safely expose LLM-backed answers while keeping privacy guarantees auditable and replayable.

This milestone closes the gap between the current retrieval pipeline and the guardrail/replay design already described in [detailed-design.md](detailed-design.md).

## Scope

```text
implement final answer guardrail validator
persist query runs for status and replay
implement replay commands for extraction, indexing, and query answering
add query-status command
add privacy leakage integration tests
```

## Non-Goals

```text
human review UI
fully deterministic replay across provider model changes
hybrid retrieval
multi-step repair loops beyond a single safe fallback path
```

## Design

### 1. Final Guardrail Validator

Guardrails run after the answer formatter or LLM answerer produces the final text.

Checks in scope:

```text
resident phone leakage
restricted email leakage
flat or address leakage
raw unsanitized snippet leakage
unsupported high-certainty process claims
restricted contact exposure when fact privacy_status forbids it
```

Guardrail actions:

```text
pass
redact
refuse_safely
```

Milestone 6 intentionally does not implement `repair_with_llm`. If a response fails guardrails and cannot be made safe with deterministic redaction, the validator returns the documented safe fallback answer.

The validator will inspect:

```text
final answer text
citations and selected facts
privacy_status on each selected fact
approved contact methods in context
```

Every validator outcome writes a `guardrail_events` row.

### 2. Query Runs

The current repo stores retrieval traces but not a durable query-run record. Milestone 6 adds `query_runs` as the user-facing ledger for query status and replay.

Proposed fields:

```text
query_id
trace_id
status
query_text_redacted
query_text_hash
query_intent
answerer_version
guardrail_version
retrieval_trace_id
final_action
created_at
completed_at
notes
```

Rules:

```text
store redacted query text, never raw text
status values: running, completed, blocked, failed
final_action values: pass, redact, refuse_safely, failed
```

### 3. Replay Commands

Replay commands provide deterministic re-entry points into later pipeline stages using already persisted sanitized inputs.

Commands in scope:

```text
aptjeeves replay-import --batch IMPORT_BATCH_ID --from-stage extraction
aptjeeves replay-fact-index --fact FACT_ID
aptjeeves replay-query --query-id QUERY_ID
aptjeeves query-status --query-id QUERY_ID
```

Replay rules:

```text
replay-import reads raw_messages for the batch and reruns extraction and indexing only
replay-fact-index refreshes the current vector entry for one canonical fact
replay-query reuses the stored redacted query text from query_runs
replay commands emit pipeline_events with stage replay
```

### 4. Testing

Required tests:

```text
guardrail blocks leaked restricted phone numbers in final answers
guardrail allows placeholder contact values such as [PHONE_1]
query-status returns retrieval and guardrail summary
replay-query produces a new query run with the same redacted query text
replay-import reruns extraction on an existing batch without re-ingesting files
```

## Exit Criteria

Milestone 6 is complete when:

```text
every ask writes a query_runs row
final answers pass through a deterministic guardrail validator
query-status and replay-query are exposed in the CLI
privacy leakage integration tests pass
```