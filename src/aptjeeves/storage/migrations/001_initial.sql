CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_runs (
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

CREATE TABLE IF NOT EXISTS raw_messages (
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

CREATE INDEX IF NOT EXISTS idx_raw_messages_import_batch
  ON raw_messages(import_batch_id);

CREATE INDEX IF NOT EXISTS idx_raw_messages_sent_at
  ON raw_messages(sent_at_utc);

CREATE TABLE IF NOT EXISTS pipeline_events (
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

CREATE INDEX IF NOT EXISTS idx_pipeline_events_trace
  ON pipeline_events(trace_id);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_import_batch
  ON pipeline_events(import_batch_id);
