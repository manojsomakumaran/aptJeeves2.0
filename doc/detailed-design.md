# AptJeeves 2.0 Detailed Design

This document expands the high-level architecture into implementation-ready design for AptJeeves 2.0.

AptJeeves 2.0 is a clean-slate LLM-based project. The rule-based/non-LLM implementation remains separate in AptJeeves 1.0 and is not part of this codebase or design.

## 1. Goals

Build a local-first, privacy-aware community knowledge assistant that can ingest exported apartment community chats and answer resident questions using grounded, cited, privacy-safe information.

Primary goals:

```text
ingest repeated monthly chat exports safely
dedupe old messages using stable message fingerprints
extract structured facts with LLM assistance
store canonical facts in SQLite as the source of truth
index sanitized facts for semantic retrieval
answer only from retrieved approved context
prevent resident PII leakage
make every important decision observable and replayable
```

Non-goals for the first implementation:

```text
no migration from AptJeeves 1.0
no RBAC or multi-user permission model
no autonomous agent framework
no cloud-hosted database requirement
no raw media processing
no official verification of government/legal information
```

## 2. System Shape

The application should be built as deterministic orchestration around a few explicit components:

```text
ChatIngestionService
MessageParser
MessageNormalizer
PrivacyRedactor
MessageDeduper
LLMExtractor
CanonicalFactStore
VectorIndexer
QueryIntentClassifier
Retriever
Reranker
ContextBuilder
LLMAnswerer
GuardrailValidator
ObservabilityService
ReplayService
```

Recommended source layout:

```text
src/
  aptjeeves/
    __init__.py
    app.py
    config.py
    cli.py
    ingestion/
      parsers.py
      normalizer.py
      fingerprint.py
      service.py
    privacy/
      detectors.py
      redactor.py
      classifier.py
      guardrails.py
    extraction/
      schemas.py
      prompts.py
      llm_extractor.py
      validator.py
    storage/
      db.py
      migrations/
      repositories.py
    indexing/
      embeddings.py
      vector_store.py
      indexer.py
    retrieval/
      intent.py
      retriever.py
      reranker.py
      context.py
    answering/
      prompts.py
      answerer.py
      formatter.py
    observability/
      events.py
      traces.py
      replay.py
tests/
  unit/
  integration/
doc/
  architecture.md
  detailed-design.md
```

## 3. Data Model

SQLite is the canonical source of truth. The vector store is only a retrieval index.

Use UUID-style string IDs for application objects and SHA-256 hex strings for stable hashes/fingerprints.

### 3.1 Import Runs

Tracks every ingestion attempt.

```sql
CREATE TABLE import_runs (
  import_batch_id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  source_file TEXT NOT NULL,
  source_file_hash TEXT NOT NULL,
  chat_name TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  status TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  normalizer_version TEXT NOT NULL,
  redactor_version TEXT NOT NULL,
  total_messages_seen INTEGER NOT NULL DEFAULT 0,
  new_messages_inserted INTEGER NOT NULL DEFAULT 0,
  duplicate_messages_skipped INTEGER NOT NULL DEFAULT 0,
  parse_failures INTEGER NOT NULL DEFAULT 0,
  extraction_failures INTEGER NOT NULL DEFAULT 0,
  notes TEXT
);
```

Status values:

```text
running
completed
completed_with_errors
failed
cancelled
```

### 3.2 Raw Messages

Stores one row per unique message. This table is the idempotency ledger.

```sql
CREATE TABLE raw_messages (
  message_id TEXT PRIMARY KEY,
  message_fingerprint TEXT NOT NULL UNIQUE,
  import_batch_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  source_conversation_id TEXT NOT NULL,
  chat_name TEXT,
  source_message_id TEXT,
  sender_hash TEXT NOT NULL,
  sender_display_hint TEXT,
  sent_at_utc TEXT NOT NULL,
  source_timezone TEXT,
  normalized_text_hash TEXT NOT NULL,
  sanitized_text TEXT NOT NULL,
  raw_text_debug_ref TEXT,
  source_file TEXT NOT NULL,
  source_offset INTEGER,
  source_line_start INTEGER,
  source_line_end INTEGER,
  processing_status TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  processed_at TEXT,
  parser_version TEXT NOT NULL,
  normalizer_version TEXT NOT NULL,
  redactor_version TEXT NOT NULL,
  FOREIGN KEY (import_batch_id) REFERENCES import_runs(import_batch_id)
);

CREATE INDEX idx_raw_messages_import_batch
  ON raw_messages(import_batch_id);

CREATE INDEX idx_raw_messages_sent_at
  ON raw_messages(sent_at_utc);
```

Processing status values:

```text
new
redacted
extracted
no_extractable_info
failed
quarantined
```

`raw_text_debug_ref` must be null by default. If a debug/quarantine mode is ever enabled, it should point to restricted local storage, not contain raw text directly.

### 3.3 Canonical Facts

Generic fact table shared by all fact types.

```sql
CREATE TABLE canonical_facts (
  fact_id TEXT PRIMARY KEY,
  fact_type TEXT NOT NULL,
  fact_identity_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  privacy_status TEXT NOT NULL,
  confidence REAL NOT NULL,
  source_count INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL,
  latest_seen TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  fact_version INTEGER NOT NULL DEFAULT 1,
  extractor_prompt_version TEXT,
  llm_model_version TEXT,
  merge_status TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX idx_canonical_facts_type
  ON canonical_facts(fact_type);

CREATE INDEX idx_canonical_facts_latest_seen
  ON canonical_facts(latest_seen);
```

Fact types:

```text
service_contact
process_info
facility_info
policy_or_rule
alert_or_issue
```

Phase 1 fact types:

```text
service_contact
process_info
facility_info
```

Privacy status values:

```text
public_to_residents
restricted_resident_pii
restricted_unknown_contact
restricted_sensitive
needs_review
```

### 3.4 Service Contacts

```sql
CREATE TABLE service_contacts (
  fact_id TEXT PRIMARY KEY,
  service_type TEXT NOT NULL,
  display_name TEXT,
  normalized_name TEXT,
  contact_methods_json TEXT NOT NULL,
  contact_method_hashes_json TEXT NOT NULL,
  contact_classification TEXT NOT NULL,
  is_resident_affiliated INTEGER NOT NULL DEFAULT 0,
  resident_affiliation_reason TEXT,
  area_or_scope TEXT,
  price_hint TEXT,
  availability_hint TEXT,
  caveats TEXT,
  FOREIGN KEY (fact_id) REFERENCES canonical_facts(fact_id)
);
```

Contact classification values:

```text
vendor_or_service_contact
resident_contact
resident_affiliated_service_contact
apartment_staff_contact
unknown_contact
```

`contact_methods_json` may contain phone/email/URL placeholders or approved service contact values. Resident phone numbers must not be returned.

### 3.5 Process Info

```sql
CREATE TABLE process_info (
  fact_id TEXT PRIMARY KEY,
  process_name TEXT NOT NULL,
  category TEXT,
  provider_or_authority TEXT,
  steps_json TEXT,
  required_documents_json TEXT,
  fees_json TEXT,
  locations_or_portals_json TEXT,
  deadlines_json TEXT,
  caveats TEXT,
  staleness_risk TEXT NOT NULL DEFAULT 'medium',
  official_verification_status TEXT NOT NULL DEFAULT 'not_verified',
  FOREIGN KEY (fact_id) REFERENCES canonical_facts(fact_id)
);
```

### 3.6 Facility Info

```sql
CREATE TABLE facility_info (
  fact_id TEXT PRIMARY KEY,
  facility_name TEXT NOT NULL,
  info_type TEXT NOT NULL,
  location_hint TEXT,
  availability TEXT,
  rules_or_steps_json TEXT,
  caveats TEXT,
  FOREIGN KEY (fact_id) REFERENCES canonical_facts(fact_id)
);
```

### 3.7 Fact Evidence

Links canonical facts to source messages.

```sql
CREATE TABLE fact_evidence (
  evidence_id TEXT PRIMARY KEY,
  fact_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  message_fingerprint TEXT NOT NULL,
  sanitized_snippet TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  confidence REAL NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (fact_id) REFERENCES canonical_facts(fact_id),
  FOREIGN KEY (message_id) REFERENCES raw_messages(message_id),
  UNIQUE (fact_id, message_id, evidence_type)
);

CREATE INDEX idx_fact_evidence_fact_id
  ON fact_evidence(fact_id);
```

Evidence types:

```text
mention
recommendation
correction
confirmation
negative_feedback
price_hint
availability_hint
```

### 3.8 Vector Entries

```sql
CREATE TABLE vector_entries (
  vector_id TEXT PRIMARY KEY,
  fact_id TEXT NOT NULL,
  fact_type TEXT NOT NULL,
  fact_version INTEGER NOT NULL,
  embedding_text TEXT NOT NULL,
  embedding_hash TEXT NOT NULL,
  embedding_model_version TEXT NOT NULL,
  vector_store_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY (fact_id) REFERENCES canonical_facts(fact_id)
);

CREATE INDEX idx_vector_entries_fact_id
  ON vector_entries(fact_id);
```

Status values:

```text
active
stale
failed
deleted
```

### 3.9 Observability Tables

```sql
CREATE TABLE pipeline_events (
  event_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  stage TEXT NOT NULL,
  severity TEXT NOT NULL,
  import_batch_id TEXT,
  message_id TEXT,
  fact_id TEXT,
  query_id TEXT,
  sanitized_payload_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_pipeline_events_trace
  ON pipeline_events(trace_id);

CREATE TABLE llm_calls (
  llm_call_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  sanitized_input_snapshot TEXT,
  sanitized_output_snapshot TEXT,
  output_json_valid INTEGER,
  latency_ms INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER,
  estimated_cost TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE retrieval_traces (
  retrieval_trace_id TEXT PRIMARY KEY,
  query_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  query_intent TEXT,
  query_embedding_hash TEXT,
  candidate_fact_ids_json TEXT NOT NULL,
  selected_fact_ids_json TEXT NOT NULL,
  removed_by_privacy_json TEXT,
  rerank_scores_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE guardrail_events (
  guardrail_event_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  query_id TEXT,
  fact_id TEXT,
  guardrail_name TEXT NOT NULL,
  action TEXT NOT NULL,
  reason TEXT NOT NULL,
  sanitized_payload_json TEXT,
  created_at TEXT NOT NULL
);
```

## 4. Ingestion Design

### 4.1 CLI Contract

Initial interface:

```text
aptjeeves ingest --apartment "Green Acres" --platform whatsapp --file "WhatsApp Chat with Apartment Main.txt"
aptjeeves ingest --apartment "Green Acres" --platform telegram --file "Telegram Chat with Apartment Main.json"
aptjeeves import-status --apartment "Green Acres" --batch IMPORT_BATCH_ID
aptjeeves replay-import --batch IMPORT_BATCH_ID --from-stage extraction
```

For multi-apartment chatbot support, each apartment should use an isolated local database:

```text
data/apartments/<apartment_slug>/aptjeeves.sqlite3
```

An explicit `--db` value remains available as an override for tests, local debugging, and one-off runs. In normal operation, `--apartment` should be the selector so data, facts, privacy decisions, and observability traces do not mix across apartments.

`--chat-name` should be optional for ingestion. When it is omitted, the CLI should infer the chat/channel name from the export filename. For example:

```text
WhatsApp Chat with Apartment Main.txt -> Apartment Main
tower-a-vendors.txt -> tower a vendors
```

If the export filename changes across monthly imports, the caller should pass a stable `--chat-name`. The chat/channel name is part of `source_conversation_id`, which is part of the fallback `message_fingerprint`. Keeping it stable is required for duplicate detection across repeated full-history imports.

Multiple chat channels from one apartment should share the same apartment database and differ only by `source_conversation_id`.

### 4.2 Ingestion Flow

```text
create import_runs row
hash source file
parse file into message candidates
normalize sender, timestamp, and text
redact sensitive values
compute message_fingerprint
insert raw_messages row
skip unique constraint conflicts as duplicates
extract facts only from newly inserted messages
upsert canonical facts
refresh vector entries for changed facts
write final import stats
```

The service should run ingestion in batches and commit at safe boundaries:

```text
import run creation: one transaction
raw message insertion: batch transactions
extraction and fact upsert: message-level or chunk-level transactions
vector refresh: fact-level transactions
```

### 4.3 Message Normalization

Normalize into an internal shape:

```json
{
  "platform": "whatsapp",
  "source_conversation_id": "sha256:...",
  "chat_name": "Apartment Main",
  "source_message_id": null,
  "sender_hash": "sha256:...",
  "sender_display_hint": "Resident A",
  "sent_at_utc": "2026-04-16T09:30:00Z",
  "source_timezone": "Asia/Kolkata",
  "normalized_text": "Contact Ramesh for plumbing. He charged Rs 500.",
  "source_file": "exports/apartment-main.txt",
  "source_offset": 12345,
  "source_line_start": 401,
  "source_line_end": 401
}
```

Normalization rules:

```text
trim leading/trailing whitespace
collapse repeated whitespace
normalize Unicode punctuation where safe
convert timestamps to UTC
preserve original source timezone
remove platform boilerplate
remove media placeholders for Phase 1
normalize sender aliases before hashing
ignore empty messages after cleanup
```

### 4.4 Message Fingerprint

If the platform has a stable native message ID:

```text
message_fingerprint = sha256(platform + source_conversation_id + source_message_id)
```

Fallback fingerprint:

```text
message_fingerprint = sha256(
  platform + "\n" +
  source_conversation_id + "\n" +
  canonical_sender + "\n" +
  normalized_sent_at_utc + "\n" +
  normalized_text_hash + "\n" +
  attachment_hashes_or_markers
)
```

Canonicalization requirements:

```text
timestamp precision should be fixed to seconds unless source has stable milliseconds
sender should be normalized before hashing
text hash should be computed after whitespace/platform cleanup
conversation ID should be derived from platform + chat name or export metadata
attachment markers should be stable placeholders in Phase 1
```

Do not use only sender + datetime. It is not stable enough for long-term dedupe.

### 4.5 Duplicate Handling

Duplicate path:

```text
attempt insert into raw_messages
if unique constraint on message_fingerprint fails:
  increment duplicate_messages_skipped
  emit duplicate_message_skipped event
  do not call extractor
```

This allows repeated monthly full imports.

### 4.6 Parse Failures

Parse failures should not fail the whole import unless the file is unreadable or the parser is clearly wrong.

For each failed message:

```text
increment parse_failures
emit parse_failure event with sanitized source metadata
continue import
```

If parse failure rate exceeds a configured threshold, mark the import as `completed_with_errors` or `failed`.

## 5. Privacy And Redaction Design

Privacy has to run before model calls, before storage/indexing, and before final answer delivery.

### 5.1 PII Detection

Deterministic detectors should identify:

```text
phone numbers
email addresses
URLs
flat numbers
tower/block identifiers
address-like strings
vehicle numbers, if obvious
names near resident markers
```

### 5.2 Placeholder Strategy

Replace detected sensitive values with typed placeholders:

```text
PHONE_1
EMAIL_1
URL_1
FLAT_1
ADDRESS_1
CONTACT_1
```

The extractor should see sanitized text:

```text
"Please contact CONTACT_1 for pest control. PHONE_1. He charged Rs 1200."
```

### 5.3 Contact Privacy Classification

Classify contacts as:

```text
vendor_or_service_contact
resident_contact
resident_affiliated_service_contact
apartment_staff_contact
unknown_contact
```

Default rule:

```text
unknown_contact => restricted_unknown_contact
resident_contact => restricted_resident_pii
resident_affiliated_service_contact => restricted unless explicit service-safe evidence exists
```

Evidence that may support service-safe classification:

```text
multiple residents recommend the same contact as a service provider
message text explicitly says plumber, electrician, cook, maid, driver, vendor, doctor, shop, security, manager
contact appears in vendor/service context rather than personal resident context
same contact is mentioned across different senders as a service
```

Evidence that should restrict:

```text
flat number near the contact
same-apartment resident marker
sender appears to share their own number
message says "my number", "call me", "I stay in", or equivalent
one-off contact with no service context
```

### 5.4 Storage Rules

Normal durable storage:

```text
sanitized text only
hashed sender IDs
hashed normalized text
approved service contact methods only when privacy_status allows
no resident phone numbers
```

Restricted debug/quarantine mode:

```text
off by default
local-only
explicitly configured
separate storage path
short retention
never used for embeddings
never used for answer context
```

## 6. LLM Extraction Design

### 6.1 Extraction Input

The extractor receives chunks of sanitized messages:

```json
{
  "trace_id": "trace_...",
  "messages": [
    {
      "message_id": "msg_...",
      "message_fingerprint": "sha256...",
      "sent_at_utc": "2026-04-16T09:30:00Z",
      "sender_hash": "sha256...",
      "sanitized_text": "Contact CONTACT_1 for plumbing. He charged Rs 500."
    }
  ]
}
```

Chunking guidance:

```text
group by conversation and nearby time window
keep chunks small enough for reliable structured extraction
include message IDs for source attribution
do not include raw PII
```

### 6.2 Extraction Output Schema

The LLM must return strict JSON.

```json
{
  "facts": [
    {
      "fact_type": "service_contact",
      "identity_key_hint": "plumber|ramesh|phone_hash_x",
      "title": "Plumber contact",
      "summary": "Residents mentioned a plumber for household plumbing work.",
      "confidence": 0.78,
      "privacy_status_hint": "needs_review",
      "source_message_ids": ["msg_123"],
      "sanitized_snippets": [
        "Contact CONTACT_1 for plumbing. He charged Rs 500."
      ],
      "service_contact": {
        "service_type": "plumber",
        "display_name": "Ramesh",
        "contact_methods": [
          {
            "type": "phone",
            "value_placeholder": "PHONE_1",
            "value_hash": "sha256...",
            "exposure_recommendation": "needs_review"
          }
        ],
        "contact_classification": "vendor_or_service_contact",
        "is_resident_affiliated": false,
        "resident_affiliation_reason": null,
        "price_hint": "Rs 500",
        "availability_hint": null,
        "caveats": null
      }
    }
  ],
  "warnings": []
}
```

For `process_info`:

```json
{
  "fact_type": "process_info",
  "identity_key_hint": "gas-address-update|indane|bangalore",
  "title": "Gas address update process",
  "summary": "Residents discussed updating the address for a gas connection.",
  "confidence": 0.71,
  "source_message_ids": ["msg_456"],
  "process_info": {
    "process_name": "Gas address update",
    "category": "utilities",
    "provider_or_authority": "Gas provider",
    "steps": ["Visit provider portal or office", "Submit proof of address"],
    "required_documents": ["Address proof"],
    "fees": [],
    "locations_or_portals": [],
    "deadlines": [],
    "caveats": "Community-discussed information only; not officially verified.",
    "staleness_risk": "high"
  }
}
```

For `facility_info`:

```json
{
  "fact_type": "facility_info",
  "identity_key_hint": "clubhouse|booking|process",
  "title": "Clubhouse booking process",
  "summary": "Residents discussed how to book the clubhouse.",
  "confidence": 0.82,
  "source_message_ids": ["msg_789"],
  "facility_info": {
    "facility_name": "Clubhouse",
    "info_type": "booking_process",
    "location_hint": null,
    "availability": null,
    "rules_or_steps": ["Contact the facility office", "Check availability"],
    "caveats": null
  }
}
```

### 6.3 Extraction Validation

Reject or quarantine extraction output when:

```text
JSON is invalid
required fields are missing
source_message_ids do not map to the input messages
raw-looking phone/email/address values appear instead of placeholders
confidence is outside 0..1
fact_type is unsupported
privacy_status_hint is invalid
```

### 6.4 Canonical Fact Upsert

The application, not the LLM, should compute the final `fact_identity_key`.

Examples:

```text
service_contact_key = sha256(service_type + normalized_name + contact_method_hashes)
process_info_key = sha256(process_name + provider_or_authority + normalized_scope)
facility_info_key = sha256(facility_name + info_type + normalized_value)
```

Merge behavior:

```text
if fact_identity_key exists:
  append fact_evidence rows
  update latest_seen
  increment source_count only for new source messages
  update summary if new evidence materially improves it
  increment fact_version if retrieval text changes
else:
  create canonical_facts row and subtype row
```

Conflicting evidence should not overwrite blindly. Store it as new evidence and lower confidence or set `needs_review` if needed.

## 7. Vector Indexing Design

Only sanitized fact text is embedded.

Embedding text template for service contacts:

```text
Fact type: service_contact
Service type: plumber
Name: Ramesh
Summary: Residents mentioned this contact for plumbing work.
Area/scope: apartment community
Evidence: 3 mentions, latest 2026-04-16
Caveats: service contact classification needs review
```

Embedding text template for process info:

```text
Fact type: process_info
Process: Gas address update
Authority/provider: Gas provider
Summary: Residents discussed updating address for gas connection.
Steps: ...
Documents: ...
Caveats: Community-discussed information only; not officially verified.
```

Refresh rules:

```text
when canonical_facts.fact_version changes, mark vector_entries stale
generate new embedding_text
compute embedding_hash
if embedding_hash changed, refresh vector store
mark vector entry active
```

Phase 1 can use a simple local vector store abstraction even if the first backend is SQLite plus an external embedding column/file. The rest of the system should depend on the abstraction, not the backend.

## 8. Query And Retrieval Design

### 8.1 Query Flow

```text
create query_id and trace_id
classify intent
redact query for logging and model calls
embed sanitized query
retrieve vector candidates
load canonical facts and subtype rows
rerank candidates
apply privacy filters
build answer context
generate grounded answer
validate final answer
return response
```

### 8.2 Intent Types

```text
find_service_contact
ask_process_steps
ask_facility_info
ask_policy_or_rule
ask_alert_or_issue
general_or_unknown
```

Intent classification may be deterministic first and LLM-assisted later.

### 8.3 Reranking Formula

Use a transparent scoring model:

```text
final_score =
  semantic_similarity * 0.45
  + source_count_score * 0.15
  + recency_score * 0.15
  + confidence_score * 0.15
  + fact_type_match_score * 0.10
  - stale_data_penalty
  - privacy_risk_penalty
```

Suggested normalization:

```text
semantic_similarity: vector score normalized 0..1
source_count_score: log-scaled mention count, capped at 1
recency_score: decay based on latest_seen
confidence_score: canonical_facts.confidence
fact_type_match_score: 1 for exact intent/fact match, 0.5 for related, 0 for unrelated
stale_data_penalty: higher for process_info with old latest_seen
privacy_risk_penalty: high for restricted or needs_review contacts
```

### 8.4 Context Builder

The answer context should be compact and structured:

```json
{
  "query_id": "query_...",
  "intent": "find_service_contact",
  "facts": [
    {
      "fact_id": "fact_...",
      "fact_type": "service_contact",
      "title": "Plumber contact",
      "summary": "...",
      "approved_contact_methods": [],
      "privacy_status": "needs_review",
      "source_count": 3,
      "latest_seen": "2026-04-16T09:30:00Z",
      "confidence": 0.78,
      "sanitized_snippets": ["..."],
      "caveats": ["Contact method not shareable until reviewed."]
    }
  ]
}
```

Never include restricted resident PII in context.

## 9. Answer Generation Design

The answerer should use a low-temperature model call with strict instructions:

```text
answer only from supplied context
do not use outside knowledge
do not expose resident phone numbers
do not expose restricted contact methods
include source count and latest mention when available
say when information is unavailable
for government/legal/admin processes, say this is community-discussed and not officially verified
```

Response shape:

```json
{
  "answer": "Residents mentioned a plumber, but the contact method is not shareable yet because it needs privacy review.",
  "citations": [
    {
      "fact_id": "fact_...",
      "source_count": 3,
      "latest_seen": "2026-04-16T09:30:00Z",
      "snippet": "Contact CONTACT_1 for plumbing."
    }
  ],
  "confidence": "medium",
  "privacy_note": "Contact method restricted pending review."
}
```

## 10. Guardrail Design

Final guardrails run after answer generation.

Checks:

```text
resident phone number leakage
restricted email leakage
flat/address leakage
raw unsanitized snippet leakage
unsupported claims not present in context
government/process over-certainty
contact method exposure when privacy_status forbids it
```

Actions:

```text
pass
redact
repair_with_llm
refuse_safely
```

Safe fallback:

```text
I found related discussion, but the contact or details appear restricted or unverified, so I cannot share them. I can share the general service/process information from the discussion.
```

Every guardrail decision must emit a `guardrail_events` row.

## 11. Observability And Replay Design

### 11.1 Trace IDs

Create a `trace_id` for:

```text
each import run
each extraction chunk
each query
each replay
```

Propagate the trace ID across events, LLM calls, retrieval traces, and guardrail events.

### 11.2 Event Style

Structured event payloads must be sanitized:

```json
{
  "event_type": "duplicate_message_skipped",
  "stage": "ingestion",
  "severity": "info",
  "import_batch_id": "import_...",
  "message_fingerprint": "sha256...",
  "reason": "message_fingerprint already exists"
}
```

### 11.3 Replay

Replay should support:

```text
replay import batch from extraction
replay single message extraction
replay fact indexing
replay query retrieval and answer generation
```

Replay inputs should be version-aware:

```text
parser_version
normalizer_version
redactor_version
extractor_prompt_version
llm_model_version
embedding_model_version
reranker_version
guardrail_version
```

## 12. Configuration

Configuration should be explicit and local-friendly:

```text
APTJEEVES_DB_PATH
APTJEEVES_DATA_DIR
APTJEEVES_VECTOR_STORE_PATH
APTJEEVES_DEFAULT_TIMEZONE
APTJEEVES_ENABLE_RAW_DEBUG_STORE=false
APTJEEVES_RAW_DEBUG_STORE_PATH
APTJEEVES_LLM_PROVIDER
APTJEEVES_LLM_MODEL
APTJEEVES_EMBEDDING_MODEL
APTJEEVES_LOG_LEVEL
```

Default timezone should be configurable. For the current deployment context, `Asia/Kolkata` is a reasonable default, but the parser should not hardcode it in a way that prevents future changes.

For multi-apartment operation, `APTJEEVES_DATA_DIR` controls the base directory used by `--apartment`. The derived DB path is:

```text
APTJEEVES_DATA_DIR/apartments/<apartment_slug>/aptjeeves.sqlite3
```

## 13. Testing Strategy

Unit tests:

```text
WhatsApp parser examples
Telegram parser examples
timestamp normalization
sender hashing
message_fingerprint stability
duplicate insert behavior
PII detectors
redaction placeholders
fact identity key generation
reranking formula
guardrail leakage checks
```

Integration tests:

```text
ingest same export twice and verify second run skips all messages
ingest expanded monthly export and verify only new messages extract
extract service contact from sanitized message
restrict resident phone number answer
retrieve process_info and include community-discussed caveat
emit import and query traces
replay a query with same retrieved facts
```

Golden test data should use fake residents, fake phone numbers, and fake chats only.

## 14. Implementation Milestones

### Milestone 1: Local Ingestion Foundation

```text
create project skeleton
create SQLite schema and migration runner
implement import_runs and raw_messages repositories
implement WhatsApp text parser
implement normalization and message_fingerprint
implement duplicate skipping
emit pipeline_events
provide aptjeeves ingest CLI
add tests for repeated imports
```

### Milestone 1.1: Telegram Ingestion Source

```text
implement Telegram JSON parser
support --platform telegram
read Telegram chat metadata when available
use Telegram native message IDs for message_fingerprint
store Telegram messages in raw_messages
preserve apartment database isolation
preserve chat/channel separation
add idempotency tests for repeated Telegram imports
```

### Milestone 2: Privacy Foundation

```text
implement PII detectors
implement sanitizer/placeholders
implement sender hashing
implement privacy-safe event payloads
add tests for phone/email/flat redaction
```

Implementation status:

```text
implemented deterministic phone/email/URL/flat/address detectors
implemented per-message typed placeholders
stores redacted text in raw_messages.sanitized_text
keeps message_fingerprint based on normalized unredacted text hash
emits redaction_counts in raw_message_inserted events
sanitizes parse failure previews before storing pipeline events
```

Still future work:

```text
resident vs vendor contact privacy classification
review workflows for restricted contacts
final answer guardrails
more advanced address detection
```

### Milestone 3: LLM Extraction And Canonical Facts

```text
define extraction JSON schemas
implement LLMExtractor abstraction
validate extraction output
implement canonical_facts and subtype repositories
implement fact_evidence
upsert service_contact, process_info, facility_info
add extraction observability
```

Implementation status:

```text
implemented canonical_facts, service_contacts, process_info, facility_info, fact_evidence tables
implemented canonical fact repository with merge/upsert behavior
implemented strict dependency-free extraction payload validator
implemented fake extractor for deterministic local tests
implemented extraction service that maps validated facts to canonical storage
implemented extract-pending CLI command using the fake extractor
marks raw messages as extracted or no_extractable_info
emits canonical_fact_upserted pipeline events
```

Still future work:

```text
real LLM provider integration
production prompts
review workflow for low-confidence/restricted facts
advanced conflict resolution
```

### Milestone 4: Vector Indexing

```text
implement embedding text builders
implement vector_entries table
implement vector store abstraction
refresh vectors after fact changes
add indexing tests
```

### Milestone 5: Retrieval And Answering

```text
implement intent classifier
implement retriever
implement reranker
implement context builder
implement answer prompt
implement final response formatter
```

### Milestone 6: Guardrails, Replay, And Hardening

```text
implement final guardrail validator
implement query traces and retrieval traces
implement replay commands
add privacy leakage integration tests
add import/query status commands
```

## 15. First Build Recommendation

Start with Milestone 1 and keep the first running product boring:

```text
one CLI command
one SQLite database
one parser path
one import ledger
one dedupe mechanism
one observability table
tests proving idempotent repeated ingestion
```

Once repeated ingestion is solid, add redaction and extraction. The LLM layer will be much easier to evolve if the ingestion spine, privacy boundaries, and traceability are already reliable.
