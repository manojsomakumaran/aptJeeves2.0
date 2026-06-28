# AptJeeves 2.0

AptJeeves 2.0 is a local-first, privacy-aware apartment community chatbot project.

The current implementation covers **Milestone 1: Local Ingestion Foundation**, **Milestone 2: Privacy Foundation**, **Milestone 3: LLM Extraction And Canonical Facts**, **Milestone 4: Vector Indexing**, **Milestone 5: Retrieval And Answering**, **Milestone 6: Guardrails, Replay, And Hardening**, and **Milestone 7: Model-Backed Intelligence**. It can ingest WhatsApp text exports and Telegram JSON exports, normalize messages, redact common sensitive values, compute stable message fingerprints, skip duplicates across repeated imports, extract canonical facts using either the fake local extractor or an OpenAI-backed extractor, index them with local token embeddings or OpenAI embeddings, answer resident questions using a deterministic retrieval-and-reranking pipeline or an OpenAI answerer, run final privacy guardrails on answers, and expose query status plus replay commands for imports, fact indexing, and queries.

## Project Layout

```text
doc/
  architecture.md
  detailed-design.md
src/
  aptjeeves/
    builders.py
    cli.py
    config.py
    answering/
    extraction/
    indexing/
    ingestion/
    observability/
    privacy/
    retrieval/
    storage/
tests/
  integration/
  unit/
```

## Configuration

AptJeeves 2.0 requires a `.env` file with API keys and model configuration.

Required/Recommended environment variables:

```text
OPENAI_API_KEY=sk-...
APTJEEVES_LLM_PROVIDER=openai
APTJEEVES_LLM_MODEL=gpt-4.1-mini
APTJEEVES_EMBEDDING_MODEL=text-embedding-3-small
APTJEEVES_EXTRACTION_BACKEND=fake
APTJEEVES_EXTRACTION_MODEL=gpt-4.1-mini
APTJEEVES_INTENT_BACKEND=keyword
APTJEEVES_INTENT_MODEL=gpt-4.1-mini
```

Optional observability:

```text
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com  (or your self-hosted instance)
```

See `.env.example` for a template.

## Run Without Installing

From the project folder:

```powershell
cd C:\Dev\aptJeeves2.0
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli --help
```

This runs directly from `src/` and does not require installing the `aptjeeves` executable.

## Optional Editable Install

If you want the `aptjeeves` command available in your active Python environment:

```powershell
cd C:\Dev\aptJeeves2.0
python -m pip install -e ".[dev]"
aptjeeves --help
```

This is optional. The no-install `python -m aptjeeves.cli ...` flow is enough for development.

## Apartment-Specific Databases

Use `--apartment` to keep each apartment chatbot isolated.

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli ingest --apartment "Green Acres" --platform whatsapp --file ".\exports\WhatsApp Chat with Apartment Main.txt"
```

This creates or uses:

```text
data/apartments/green-acres/aptjeeves.sqlite3
```

Another apartment name creates a different database:

```powershell
python -m aptjeeves.cli ingest --apartment "Lake View" --platform whatsapp --file ".\exports\WhatsApp Chat with Apartment Main.txt"
```

Database path:

```text
data/apartments/lake-view/aptjeeves.sqlite3
```

You can change the base data folder:

```powershell
$env:APTJEEVES_DATA_DIR = "C:\AptJeevesData"
```

Then apartment databases are created under:

```text
C:\AptJeevesData\apartments\<apartment_slug>\aptjeeves.sqlite3
```

## Manual DB Override

Use `--db` when you want a specific SQLite file, usually for tests or one-off debugging:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli --db .\scratch.sqlite3 ingest --platform whatsapp --file ".\exports\WhatsApp Chat with Apartment Main.txt"
```

`--db` takes precedence over `--apartment`.

## Ingest A WhatsApp Export

Expected command:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli ingest --apartment "Green Acres" --platform whatsapp --file ".\exports\WhatsApp Chat with Apartment Main.txt"
```

`--chat-name` is optional. If you omit it, AptJeeves infers the chat/channel name from the export filename. For example:

```text
WhatsApp Chat with Apartment Main.txt -> Apartment Main
tower-a-vendors.txt -> tower a vendors
```

Use `--chat-name` only when the filename is not stable or not meaningful:

```powershell
python -m aptjeeves.cli ingest --apartment "Green Acres" --platform whatsapp --file .\exports\april-export.txt --chat-name "Apartment Main"
```

This matters for dedupe: the chat/channel identity is part of `message_fingerprint`. If the same chat is imported monthly with different filenames, pass the same `--chat-name` each time.

Other optional flags for `ingest`:

```text
--timezone TZ      Timezone for parsing timestamps (e.g., "UTC", "America/New_York")
--date-order FMT   Order for ambiguous dates like 01/02/03 (DMY or MDY, default: DMY)
--upload-dir PATH  Directory with uploaded attachments (e.g., .vcf files)
```

## Ingest A Telegram Export

Telegram Desktop can export chat history as JSON. Use that JSON file with `--platform telegram`:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli ingest --apartment "Green Acres" --platform telegram --file .\exports\result.json
```

Telegram JSON exports usually include the chat name and stable message IDs, so `--chat-name` is normally not needed. AptJeeves will use Telegram's native message IDs for stronger duplicate detection.

If the Telegram JSON does not contain a useful chat name, pass one explicitly:

```powershell
python -m aptjeeves.cli ingest --apartment "Green Acres" --platform telegram --file .\exports\result.json --chat-name "Apartment Main"
```

Example JSON output:

```json
{
  "import_batch_id": "import_abc123",
  "status": "completed",
  "total_messages_seen": 42,
  "new_messages_inserted": 42,
  "duplicate_messages_skipped": 0,
  "parse_failures": 0,
  "db_path": "data\\apartments\\green-acres\\aptjeeves.sqlite3",
  "chat_name": "Apartment Main"
}
```

If you run the same import again, old messages should be skipped:

```json
{
  "status": "completed",
  "total_messages_seen": 42,
  "new_messages_inserted": 0,
  "duplicate_messages_skipped": 42,
  "parse_failures": 0
}
```

That duplicate protection is based on `message_fingerprint`.

## Privacy Redaction

Before messages are stored in `raw_messages.sanitized_text`, AptJeeves redacts common sensitive values with typed placeholders.

Example input:

```text
Call Ramesh 9876543210 from B-1204 or ramesh@example.com
```

Stored sanitized text:

```text
Call Ramesh PHONE_1 from FLAT_1 or EMAIL_1
```

Current deterministic detectors cover:

```text
Indian phone numbers
email addresses
URLs
flat/unit numbers such as B-1204 or flat A-1001
simple tower/block/building markers
```

`message_fingerprint` still uses the normalized unredacted text hash. That is intentional: improving redaction rules later should not change duplicate detection for already-seen messages.

## Multiple Chats Per Apartment

Multiple chat channels from the same apartment go into the **same apartment database**.

For example:

```powershell
python -m aptjeeves.cli ingest --apartment "Green Acres" --platform whatsapp --file ".\exports\WhatsApp Chat with Apartment Main.txt"

python -m aptjeeves.cli ingest --apartment "Green Acres" --platform whatsapp --file ".\exports\WhatsApp Chat with Tower A Vendors.txt"
```

Both use:

```text
data/apartments/green-acres/aptjeeves.sqlite3
```

But they are stored as separate source conversations:

```text
Apartment Main
Tower A Vendors
```

So the split is:

```text
--apartment = database boundary
chat name = channel/conversation boundary inside that database
```

## Check Import Status

Use the `import_batch_id` from ingest output:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli import-status --apartment "Green Acres" --batch import_abc123
```

If you used `--db` during ingest, use the same `--db` during status lookup:

```powershell
python -m aptjeeves.cli --db .\scratch.sqlite3 import-status --batch import_abc123
```

## Check Query Status

Retrieve status and safety/auditing metrics for a past resident query using the `query_id`:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli query-status --apartment "Green Acres" --query-id query_abc123
```

## Replay Operations

Replay commands provide deterministic re-entry points into later pipeline stages using already-persisted, sanitized inputs.

### Replay Import
Rerun extraction and indexing for an existing import batch without re-ingesting the raw source files:
```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli replay-import --apartment "Green Acres" --batch import_abc123 --from-stage extraction
```

### Replay Fact Indexing
Rerun vector indexing for a single canonical fact to refresh its vector store entry:
```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli replay-fact-index --apartment "Green Acres" --fact fact_abc123
```

### Replay Query
Replay a query from its stored redacted text, generating a new query run:
```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli replay-query --apartment "Green Acres" --query-id query_abc123
```


## Extract Pending Facts

After ingestion, run extraction over pending raw messages:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli extract-pending --apartment "Green Acres"
```

For a manual DB:

```powershell
python -m aptjeeves.cli --db .\scratch.sqlite3 extract-pending
```

Extraction uses LLM-assisted extraction with deterministic safety controls. The system applies privacy redaction before sending text to the LLM, extracts typed knowledge objects (service contacts, process information, facility details), and stores them with confidence scores and source tracking.

Example output:

```json
{
  "status": "completed",
  "facts_upserted": 1,
  "fact_ids": ["fact_abc123"],
  "db_path": "data\\apartments\\green-acres\\aptjeeves.sqlite3",
  "extraction_model": "gpt-4-mini"
}
```

Extracted facts are stored in:

```text
canonical_facts
service_contacts
process_info
facility_info
fact_evidence
```

## Index Facts

After extraction, create or refresh vector entries:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli index-facts --apartment "Green Acres"
```

For a manual DB:

```powershell
python -m aptjeeves.cli --db .\scratch.sqlite3 index-facts
```

Indexing uses OpenAI's text-embedding-3-small model to generate semantic embeddings for sanitized fact text. Vector entries point back to canonical facts in the database. Local vector index is used only for semantic retrieval; the database remains the source of truth.

Example output:

```json
{
  "status": "completed",
  "vectors_upserted": 1,
  "vector_ids": ["vector_abc123"],
  "db_path": "data\\apartments\\green-acres\\aptjeeves.sqlite3",
  "embedding_model": "text-embedding-3-small"
}
```

Vector entries are stored in:

```text
vector_entries
```

The current local workflow is:

```powershell
python -m aptjeeves.cli ingest --apartment "Green Acres" --platform whatsapp --file ".\exports\WhatsApp Chat with Apartment Main.txt"
python -m aptjeeves.cli extract-pending --apartment "Green Acres"
python -m aptjeeves.cli index-facts --apartment "Green Acres"
```

## Ask A Question

After ingestion, extraction, and indexing, ask a question:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli ask --apartment "Green Acres" "Who is a good plumber?"
```

For a manual DB:

```powershell
python -m aptjeeves.cli --db .\scratch.sqlite3 ask "How to update gas address?"
```

Optional flags:

```text
--top-k N       Maximum retrieval candidates (default: 10)
--max-facts N   Maximum facts in the answer (default: 5)
```

The answer is generated using gpt-4-mini with retrieved context only. Privacy filters are applied throughout retrieval and final guardrails validate the response before returning it.

Example JSON output:

```json
{
  "answer": "Residents mentioned a plumber contact.\nPlumber\nMentioned by 3 source(s), last seen 2026-04-16T09:30:00Z.",
  "citations": [
    {
      "fact_id": "fact_abc123",
      "source_count": 3,
      "latest_seen": "2026-04-16T09:30:00Z",
      "snippet": "Call PHONE_1 for plumbing."
    }
  ],
  "confidence": "medium",
  "privacy_note": "Some contact details are restricted pending privacy review.",
  "query_id": "query_abc123",
  "intent": "find_service_contact"
}
```

The retrieval pipeline is fully deterministic (no LLM calls). It uses keyword-based intent classification, token-vector cosine similarity retrieval, transparent metadata reranking, and template-based answer formatting.

## Observability, Tracing, and Logging

AptJeeves 2.0 incorporates three main layers of observability, tracking, and logging for production readiness and offline safety.

### 1. Centralized Debug Logging
A centralized file-logging setup is configured at the root package level ([__init__.py](file:///C:/Dev/aptJeeves2.0/src/aptjeeves/__init__.py)). All CLI commands, background processes, and API server requests log detailed debug logs directly to a shared `aptjeeves_debug.log` file in the project's root folder.

### 2. SQLite Pipeline Events
For database-backed pipeline observability, AptJeeves writes structured, privacy-safe lifecycle events to the database (`pipeline_events` table). This includes tracking background tasks (e.g., `background_task_started`, `background_task_completed`, `background_task_failed`) and operations replay logs.

You can view these events using the CLI `show-events` command:

```powershell
$env:PYTHONPATH = ".\src"
python -m aptjeeves.cli show-events --apartment "Green Acres" --limit 5
```

This command prints a JSON list of recent events (with the `--limit` flag controlling the number of records shown) and is highly useful for tracing retrieval, extractions, and guardrail validations.

### 3. Langfuse LLM Tracing
If `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are provided in the environment/`.env`, AptJeeves uses the official Langfuse SDK to trace all LLM operations (such as LLM extraction, intent classification, and question answering).
- **Wrapped Clients**: LLM components use Langfuse's wrapped OpenAI client.
- **Decorators**: Key entry points and pipeline stages are decorated with `@observe()` to automatically log token usage, API costs, execution latency, inputs, and outputs.
- **Offline Null Fallback**: If Langfuse keys are absent, a local `NullLangfuseClient` intercepts the tracing commands, preventing external network overhead and avoiding failures.

## Environment Variables From .env

AptJeeves loads environment variables from a `.env` file in the project root. Existing environment variables are not overwritten. Copy `.env.example` to `.env` and fill in your values.

## Run Tests

From the project folder:

```powershell
cd C:\Dev\aptJeeves2.0
python -m pytest
```

If imports fail because the package is not installed, run tests with `PYTHONPATH`:

```powershell
$env:PYTHONPATH = ".\src"
python -m pytest
```

Current test coverage includes:

```text
WhatsApp parser behavior
Telegram parser behavior
multiline message handling
timestamp normalization
phone/email/URL/flat/address redaction
sanitized storage for WhatsApp and Telegram
canonical fact upsert/merge behavior
fake extraction into service/process/facility facts
local vector indexing for canonical facts
apartment DB path resolution
idempotent repeated imports
expanded monthly imports that add only new messages
CLI ingest JSON output
.env file loading
keyword intent classification
cosine similarity retrieval
reranking formula scoring
template-based answer formatting
full ask pipeline integration
retrieval trace persistence
CLI ask JSON output
offline testing safety (auto-mocking/disabling external calls to OpenAI and Langfuse)
```

## Useful Environment Variables

```text
APTJEEVES_DB_PATH              Default SQLite DB when neither --db nor --apartment is provided
APTJEEVES_DATA_DIR             Base folder for apartment-specific databases
APTJEEVES_DEFAULT_TIMEZONE     Default timezone for parsing chat timestamps
APTJEEVES_LOG_LEVEL            Reserved for logging configuration
APTJEEVES_LLM_PROVIDER         LLM provider (default: openai)
APTJEEVES_LLM_MODEL            LLM model for answering (default: gpt-4.1-mini)
APTJEEVES_EMBEDDING_MODEL      Embedding model version (default: text-embedding-3-small)
APTJEEVES_EXTRACTION_BACKEND   Extraction backend to use: fake or openai (default: fake)
APTJEEVES_EXTRACTION_MODEL     Model for LLM extraction (default: gpt-4.1-mini)
APTJEEVES_INTENT_BACKEND       Intent classification backend: keyword or openai (default: keyword)
APTJEEVES_INTENT_MODEL         Model for LLM intent classification (default: gpt-4.1-mini)
OPENAI_API_KEY                 API key for OpenAI services
LANGFUSE_PUBLIC_KEY            Public key for Langfuse observability
LANGFUSE_SECRET_KEY            Secret key for Langfuse observability
LANGFUSE_HOST                  Host for Langfuse observability (e.g., https://cloud.langfuse.com)
```

Defaults:

```text
APTJEEVES_DB_PATH=aptjeeves.sqlite3
APTJEEVES_DATA_DIR=data
APTJEEVES_DEFAULT_TIMEZONE=Asia/Kolkata
APTJEEVES_LOG_LEVEL=INFO
APTJEEVES_LLM_PROVIDER=openai
APTJEEVES_LLM_MODEL=gpt-4.1-mini
APTJEEVES_EMBEDDING_MODEL=text-embedding-3-small
APTJEEVES_EXTRACTION_BACKEND=fake
APTJEEVES_EXTRACTION_MODEL=gpt-4.1-mini
APTJEEVES_INTENT_BACKEND=keyword
APTJEEVES_INTENT_MODEL=gpt-4.1-mini
```

## Design Docs

Start here for the architecture and implementation plan:

```text
doc/architecture.md
doc/detailed-design.md
```

## Web Interface (UI & FastAPI Backend)

AptJeeves 2.0 includes a local FastAPI backend and a Vite-based React Single Page Application (SPA) frontend.

### 1. Launch the Backend Server
Run the FastAPI application from the project root:
```powershell
$env:PYTHONPATH = ".\src"
python -m uvicorn aptjeeves.api.server:app --host 127.0.0.1 --port 8000
```
This runs the backend at `http://127.0.0.1:8000` with the following endpoints:
- `POST /api/{apartment}/ask` — Submit questions to the LLM or template answering pipeline.
- `GET /api/apartments` — List all available apartment databases.
- `GET /api/{apartment}/status` — Fetch ingestion, extraction, and vector metrics.
- `GET /api/{apartment}/settings` & `POST /api/{apartment}/settings` — Manage configuration preferences.
- `POST /api/{apartment}/reset-failed` — Re-queue failed extractions.
- `POST /api/{apartment}/upload` — Process multi-file WhatsApp/Telegram log uploads and queue background processing.
- `GET /api/{apartment}/observability` — Monitor API token usage, costs, and latencies.
- `GET /api/{apartment}/logs` — Retrieve DB pipeline events.

### 2. Launch the React Frontend
Navigate to the `frontend` folder and run the dev server:
```powershell
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173/` in your browser.

### 3. UI Features
- **Interactive Chat Interface**: Chat with the AptJeeves assistant, explore citations, inspect confidence ratings, and view privacy warnings.
- **Folder Ingestion & Pipeline Status**: Upload raw logs directly, trigger pipelines, and watch progress bars update in real-time.
- **Observability Dashboard**: Track LLM usage costs and latency per operation.
- **System Statistics**: Monitor total active vectors, extracted facts, and pending items.
- **Advanced Configuration**: Edit settings (like embedding and extraction models) per apartment, or reset failed extraction messages to requeue them safely without waste.

## Current Scope

All core milestones (1 through 8) are now fully implemented:

```text
SQLite schema and migration runner
WhatsApp text ingestion
Telegram JSON ingestion
message normalization
privacy redaction into sanitized_text
canonical fact storage
fake and OpenAI-backed extraction backends
local token-vector and OpenAI semantic embedding indexers
message_fingerprint dedupe
apartment-specific database selection
privacy-safe pipeline events
CLI ingest and import-status commands
tests for repeated and expanded imports
.env file loading into config
keyword-based and OpenAI LLM intent classifiers
token-vector and semantic cosine similarity retrieval
transparent metadata reranker
structured context builder with privacy filtering
template-based and LLM-based answer formatters
query runs, retrieval traces, and guardrail events persistence
final privacy guardrail validators (verifies phone, email, unit, and fact privacy statuses)
replay commands for import batches, facts, and queries
CLI ask, query-status, and replay commands with JSON output
FastAPI backend server endpoints and asynchronous tasks
React frontend SPA with chat interface, ingestion, usage, and logs views
centralized component builder factory pattern (builders.py)
Langfuse cloud tracing integration for LLM calls with offline fallback
centralized debug file logging (aptjeeves_debug.log)
extended pipeline events with status mapping and background task tracking
```
