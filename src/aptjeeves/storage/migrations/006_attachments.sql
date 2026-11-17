CREATE TABLE IF NOT EXISTS attachments (
  attachment_id TEXT PRIMARY KEY,
  content_sha256 TEXT NOT NULL UNIQUE,
  original_filename TEXT NOT NULL,
  mime_sniffed TEXT,
  size_bytes INTEGER,
  page_count INTEGER,
  spool_path TEXT,
  extraction_method TEXT,
  status TEXT NOT NULL,
  status_reason TEXT,
  text_chars INTEGER,
  segment_count INTEGER,
  extractor_version TEXT,
  first_seen_at TEXT NOT NULL,
  processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_attachments_status
  ON attachments(status);

CREATE TABLE IF NOT EXISTS attachment_links (
  attachment_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  PRIMARY KEY (attachment_id, message_id),
  FOREIGN KEY (attachment_id) REFERENCES attachments(attachment_id),
  FOREIGN KEY (message_id) REFERENCES raw_messages(message_id)
);

ALTER TABLE raw_messages ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'chat';
ALTER TABLE raw_messages ADD COLUMN parent_message_id TEXT;
ALTER TABLE raw_messages ADD COLUMN attachment_id TEXT;
ALTER TABLE raw_messages ADD COLUMN segment_label TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_messages_attachment
  ON raw_messages(attachment_id);
