-- Original PHONE/EMAIL values behind the placeholders in raw_messages.sanitized_text.
-- Local only: never sent to an LLM, embedded, logged or put in events. Used to
-- restore service-contact numbers into final answers.
CREATE TABLE IF NOT EXISTS message_pii (
  message_id TEXT NOT NULL,
  placeholder TEXT NOT NULL,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (message_id, placeholder),
  FOREIGN KEY (message_id) REFERENCES raw_messages(message_id)
);
