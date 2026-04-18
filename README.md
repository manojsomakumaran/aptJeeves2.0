# AptJeeves 2.0

AptJeeves 2.0 is a local-first, privacy-aware apartment community chatbot project.

The current implementation covers **Milestone 1: Local Ingestion Foundation** and **Milestone 2: Privacy Foundation**. It can ingest WhatsApp text exports and Telegram JSON exports, normalize messages, redact common sensitive values, compute stable message fingerprints, skip duplicates across repeated imports, and store import observability events in SQLite.

## Project Layout

```text
doc/
  architecture.md
  detailed-design.md
src/
  aptjeeves/
    cli.py
    config.py
    ingestion/
    observability/
    storage/
tests/
  integration/
  unit/
```

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

Current extraction uses a deterministic fake extractor. It is intentionally not a real LLM call yet. The fake extractor is useful for testing the storage contract and merge behavior before adding model/API dependencies.

Example output:

```json
{
  "status": "completed",
  "facts_upserted": 1,
  "fact_ids": ["fact_abc123"],
  "db_path": "data\\apartments\\green-acres\\aptjeeves.sqlite3",
  "extractor": "fake"
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
apartment DB path resolution
idempotent repeated imports
expanded monthly imports that add only new messages
CLI ingest JSON output
```

## Useful Environment Variables

```text
APTJEEVES_DB_PATH              Default SQLite DB when neither --db nor --apartment is provided
APTJEEVES_DATA_DIR             Base folder for apartment-specific databases
APTJEEVES_DEFAULT_TIMEZONE     Default timezone for parsing chat timestamps
APTJEEVES_LOG_LEVEL            Reserved for logging configuration
```

Defaults:

```text
APTJEEVES_DB_PATH=aptjeeves.sqlite3
APTJEEVES_DATA_DIR=data
APTJEEVES_DEFAULT_TIMEZONE=Asia/Kolkata
APTJEEVES_LOG_LEVEL=INFO
```

## Design Docs

Start here for the architecture and implementation plan:

```text
doc/architecture.md
doc/detailed-design.md
```

## Current Scope

Implemented:

```text
SQLite schema and migration runner
WhatsApp text ingestion
Telegram JSON ingestion
message normalization
privacy redaction into sanitized_text
canonical fact storage
fake extractor and extraction validation contract
message_fingerprint dedupe
apartment-specific database selection
privacy-safe pipeline events
CLI ingest and import-status commands
tests for repeated and expanded imports
```

Not implemented yet:

```text
real LLM extraction provider
vector indexing
retrieval and answer generation
final privacy guardrails
resident vs vendor contact privacy classification
replay commands
```
