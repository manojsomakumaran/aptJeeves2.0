# Attachment Ingestion Design

Status: Phases 1 and 2 implemented (decisions confirmed 2026-11-14)

## 1. Goal

Today, chat attachments (documents, PDFs, pictures) are ignored. Media-only messages are dropped in
`ingestion/normalizer.py`, and only `.vcf` files are resolved and parsed. This design extracts text from
attachments and feeds it through the existing pipeline so it can produce `service_contact`,
`process_info` and `facility_info` facts.

## 2. Confirmed decisions

| Topic | Decision |
|---|---|
| Platform | **WhatsApp first**; Telegram in a later phase |
| Image OCR | **Phase 2** (Phase 1 = PDF / Office / text files only) |
| OCR engine | **Local only**. No raw image or document content is ever sent to an external provider |
| Original files | **Kept** in the first iteration; a config option controls spool cleanup later |
| Bills / leases | **Skipped as sensitive** (not redacted-and-processed) |

## 3. Invariants preserved

- SQLite is the source of truth; the vector index is only for lookup.
- Only **sanitized text** reaches any external model. Attachment text is redacted before extraction.
- Ingestion is idempotent: re-importing the full chat history never reprocesses a known attachment.

## 4. Flow

```text
WhatsApp export + attachment folder
  -> discover attachment references in message text   (filename pattern "(file attached)")
  -> resolve file in attachment folder (existing tolerant filename matching)
  -> sniff real type by magic bytes, compute sha256
  -> copy into content-addressed spool: data/apartments/<slug>/attachments/<sha256>.<ext>
  -> record in attachments / attachment_links           (status=pending)
  -> [attachments stage] extract text by type
  -> sensitive-document check                            (skip bills/leases/ID docs)
  -> redact (existing redactor)
  -> chunk into segments (page/section aware, size-bounded)
  -> insert segments as raw_messages rows (source_kind='attachment')
  -> existing: extract -> canonical_facts -> index -> retrieval
```

Pipeline order becomes: **ingest -> attachments -> extract -> index**.

## 5. Data model (migration `006_attachments.sql`)

New tables:

```text
attachments(
  attachment_id        TEXT PRIMARY KEY,        -- att_<sha256[:32]>
  content_sha256       TEXT NOT NULL UNIQUE,
  original_filename    TEXT NOT NULL,           -- first name seen
  mime_sniffed         TEXT,
  size_bytes           INTEGER,
  page_count           INTEGER,
  spool_path           TEXT,                    -- NULL once spool cleanup is enabled and has run
  extraction_method    TEXT,                    -- native_text | local_ocr (phase 2)
  status               TEXT NOT NULL,           -- see 5.1
  status_reason        TEXT,
  text_chars           INTEGER,
  extractor_version    TEXT,
  first_seen_at        TEXT NOT NULL,
  processed_at         TEXT
)

attachment_links(
  attachment_id        TEXT NOT NULL,
  message_id           TEXT NOT NULL,           -- parent chat message
  PRIMARY KEY (attachment_id, message_id)
)
```

Changes to `raw_messages`:

```text
source_kind          TEXT NOT NULL DEFAULT 'chat'    -- 'chat' | 'attachment'
parent_message_id    TEXT                            -- chat message that referenced the file
attachment_id        TEXT
segment_label        TEXT                            -- e.g. "p.2" or "sheet:Rates"
```

### 5.1 Attachment statuses

`pending`, `text_extracted`, `no_text`, `skipped_unsupported`, `skipped_too_large`,
`skipped_sensitive`, `skipped_missing_file`, `failed`.

`failed` is retryable via the existing `reset-failed` pattern.

### 5.2 Segment identity (idempotency)

```text
segment fingerprint = hash(attachment content_sha256, parent source_conversation_id, segment_index)
message_id          = msg_<fingerprint[:32]>
```

The same file forwarded into the chat many times is **one** `attachments` row, many `attachment_links`, and one
set of segments. Re-imports hit the UNIQUE fingerprint and are skipped. The segment inherits the **earliest**
linked parent's sender hash and timestamp.

## 6. Text extraction (Phase 1)

| Type | Method | Library |
|---|---|---|
| PDF with text layer | per-page native text | `pdfplumber` |
| DOCX | paragraphs + tables | `python-docx` |
| XLSX / CSV | per-sheet rows rendered as text | `openpyxl`, stdlib `csv` |
| TXT / MD | decode with fallback encodings | stdlib |
| Scanned PDF, images | **Phase 2** (local OCR) | RapidOCR or Tesseract |
| Video, audio, stickers, other | `skipped_unsupported` | |

Type is decided by magic bytes, not by extension. A PDF with almost no text layer is marked `no_text` in
Phase 1 and becomes an OCR candidate in Phase 2.

Optional dependencies (`pdfplumber`, `python-docx`, `openpyxl`) live in a new `attachments` extra in
`pyproject.toml` (also included in `dev`) so the core install stays light.

## 7. Safety and privacy

**Sensitive-document skip.** After text extraction and before redaction, a detector scores the document. A
document is `skipped_sensitive` (no segments created, text discarded) when any of these hold:
- ID-number patterns (Aadhaar/PAN-style, passport-like), bank account / IFSC / card-like numbers
- bill or invoice markers (e.g. "amount due", "bill date", "consumer no.", "invoice no.") combined with
  resident-identifying content
- lease markers ("lessor", "lessee", "rent agreement", "security deposit", "tenancy")
- PII density (phones, emails, flat/address markers per 1,000 chars) above a configurable threshold

Detector rules live in `privacy/detectors.py` beside the existing ones and are unit-tested with fixtures. The
reason is recorded in `status_reason` (a category only, never the matched text).

**Untrusted input.** Documents are treated as hostile:
- size cap (default 20 MB) and page cap (default 50) per file; text cap per document
- per-file extraction timeout; run extraction in a subprocess so a parser crash or hang cannot take down the server
- no macros, external links or embedded objects are followed
- password-protected / corrupt files -> `failed` with a reason

**Prompt injection.** Document text is passed as data. The extraction prompt states that content inside
documents is never instructions. Schema validation and the final guardrails already bound the impact.

**Original files.** Kept in the spool for now (`spool_path` populated). Because they may contain PII, the spool
lives under the per-apartment data directory and is excluded from git (verify `.gitignore` covers
`data/`). Config option for later cleanup:

```text
APTJEEVES_ATTACHMENT_RETENTION=keep            # keep (default) | delete_after_extract
```

When `delete_after_extract` is enabled, the file is removed after a terminal status is reached and
`spool_path` is set to NULL.

## 8. Extraction changes

- `MessageForExtraction` gains `source_kind`, `attachment_name`, `segment_label`.
- **Chunking.** Chat keeps count-based chunks (75 messages, overlap 5). Attachment segments use size-based
  chunking (about 3-4k characters, split on page and heading boundaries, small overlap) and are sent in
  **separate LLM calls** from chat.
- **Prompt.** A document variant of the prompt: documents are denser, so extract many facts per segment; keep page
  labels in snippets; `official_verification_status` may be `verified` only when the document is clearly
  official (society notice, rules). The prompt version is bumped.
- **Noise filter.** The existing `_is_noise_message` still applies. Segments with very little text are skipped
  and tagged `skipped_noise_filter`.
- **Fact merging.** Unchanged. A vendor in a rate card and the same vendor in chat merge through
  `identity_key_hint` and raise `source_count`.
- **Evidence.** Snippets cite attachment name and page, so answers can say "from *Clubhouse Rules.pdf*, p.2".

## 9. API / CLI / frontend

- **Upload endpoint.** `/upload` currently deletes its temp dir in `finally`, before background tasks run.
  Attachments must therefore be **copied into the spool during ingest**, before the temp dir is removed.
  The background task chain becomes attachments -> extract -> index.
- **CLI.** Reuse `ingest --attachments-dir`; add `process-attachments [--limit N]`; `reset-failed` also resets
  failed attachments; `import-status` shows attachment counts.
- **Status/observability.** Counts per attachment status in `/status` and `/observability`.
- **Events.** `attachment_discovered`, `attachment_deduped`, `attachment_text_extracted`, `attachment_skipped`
  (with reason category), `attachment_failed`.
- **Frontend.** An "Attachments" progress card in the pipeline view (counts by status, plus OCR counts from Phase 2).

## 10. WhatsApp discovery details

- A WhatsApp export with media renders attachments as lines like `IMG-2024...jpg (file attached)` or
  `Rules.pdf (file attached)`. The existing `_extract_vcard_filename` logic generalizes to any filename with a
  supported extension, with captions possibly on following lines.
- Messages with `<Media omitted>` have no resolvable file and remain ignored.
- Filename resolution reuses the tolerant matcher (`_resolve_vcard_path`, NFKC + casefold), renamed to a
  generic attachment resolver.
- A referenced file missing from the folder -> `skipped_missing_file` event, no failure.

Telegram (later phase): the JSON export carries relative paths in `file` / `photo` fields, so resolution is
direct. It reuses everything downstream of discovery.

## 11. Phasing

**Phase 1 (WhatsApp, no OCR)**
1. Migration `006`, repositories, models
2. Discovery + resolver generalization + spool + magic-byte sniffing
3. Extractors: PDF, DOCX, XLSX/CSV, TXT (subprocess-isolated)
4. Sensitive-document detector
5. Segmenting + insertion as `raw_messages`
6. Extraction prompt/schema/chunking changes
7. Attachments stage wired into CLI, `/upload` and the status API; frontend counts
8. Tests (below)

**Phase 2 (WhatsApp OCR)**: local OCR backend (`APTJEEVES_ATTACHMENT_OCR_BACKEND=none|local`), images, scanned
PDFs via page rendering, image skip heuristics (memes/selfies), OCR confidence thresholds.

**Phase 3**: Telegram discovery. (`delete_after_extract` spool cleanup was delivered in Phase 1.)

## 12. Test plan

Unit:
- magic-byte type sniffing (extension mismatch, corrupt files)
- PDF / DOCX / XLSX / CSV / TXT extraction on small fixtures
- sensitive-document detector (bill, lease, ID, clean rate card)
- segment chunking boundaries, segment fingerprint stability
- WhatsApp attachment-line discovery incl. odd filenames and Unicode marks

Integration:
- ingest -> attachments -> extract with the fake extractor produces facts with attachment evidence
- same file forwarded 3 times -> 1 attachment, 3 links, one set of segments
- full re-import is idempotent
- sensitive document -> `skipped_sensitive`, zero segments, no text persisted
- failed attachment -> `reset-failed` -> retry succeeds
- `/upload` flow keeps files available for the background stages

## 13. Open items (non-blocking)

- Default thresholds for the sensitive detector and PII density; tune against real exports.
- OCR confidence/size/text thresholds; tune against real exports (tests use a fake backend).
- Surface page labels in answer text (stored on each segment, not yet cited).

Resolved: very large spreadsheets are truncated to a row cap (default 500) and marked `truncated`; the spool
lives in an `attachments/` folder beside the SQLite file, so `--db` overrides work.

## 14. As-built notes (Phase 1)

- Code lives in `src/aptjeeves/attachments/` (`discovery`, `sniff`, `extractors`, `worker`, `sensitive`,
  `chunking`, `repository`, `service`, `config`). Migration: `006_attachments.sql`.
- The spool defaults to an `attachments/` folder beside the SQLite file (so `--db` overrides work too).
- `process-attachments` (CLI) and `POST /api/{apartment}/attachments/process` run the stage; `/upload`
  chains attachments -> extraction -> indexing. `/status` reports counts per attachment status and
  `reset-failed` also requeues failed attachments.
- Extraction prompt version is now `extractor_contract_openai_v2`; document segments use a larger output
  budget and are chunked at ~8,000 characters per call, never mixed with chat.
- `/upload` now passes the uploaded files (or the optional `attachment_folder`) as the attachment source;
  this also lets vCard files uploaded with the export be parsed.
- Spool cleanup (`delete_after_extract`) is implemented, but only for `text_extracted` and
  `skipped_sensitive`; images and `no_text` files are kept for Phase 2 OCR.
- Not yet done: Telegram attachment discovery (Phase 3), page citations in answer text (the page label is
  stored on each segment but not yet surfaced in answers). Image/scan OCR was delivered in Phase 2 (section 15).

## 15. As-built notes (Phase 2)

- `attachments/ocr.py`: backend abstraction; `APTJEEVES_ATTACHMENT_OCR_BACKEND=none|local`. `local` uses
  RapidOCR (`pip install ".[ocr]"`), imported lazily. Local only; nothing is sent to a provider.
- OCR runs inside the isolated worker subprocess (separate `APTJEEVES_ATTACHMENT_OCR_TIMEOUT_SECONDS`, 180s,
  because the model loads on first use).
- Images: skipped if the shorter side is under 200 px (icons/stickers); lines below the confidence threshold
  (0.6) are dropped; OCR text under 30 characters means photo/meme/selfie, so the file ends `no_text`.
- Scanned PDFs: only pages with almost no native text are rendered (200 dpi via pdfplumber) and OCRed, up to
  `OCR_MAX_PAGES` per file (10); a cap hit marks the result truncated. Method is `local_ocr` when any page used OCR.
- OCR output goes through the same sensitive-document check and redaction as native text before segmenting.
- Parked files are re-queued automatically (`requeue_for_ocr`): images with `image_ocr_not_enabled` and PDFs
  `no_text` with no extraction method, on the next `process-attachments` once OCR is enabled.
- A `no_text_after_ocr` result is terminal, so its spool file is eligible for `delete_after_extract`.
- If OCR is selected but not installed the file fails with `ocr_unavailable` (retry via `reset-failed`).
- Extractor version bumped to `attachment_text_v2`.
- `/status` also returns `attachment_ocr` (backend, OCR-read, OCR-no-text, awaiting-OCR, engine-missing counts);
  the Attachments card shows them.
- Not verified: real RapidOCR output quality. Tests use a fake backend; tune thresholds against real exports.
