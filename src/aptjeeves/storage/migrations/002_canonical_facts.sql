CREATE TABLE IF NOT EXISTS canonical_facts (
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

CREATE INDEX IF NOT EXISTS idx_canonical_facts_type
  ON canonical_facts(fact_type);

CREATE INDEX IF NOT EXISTS idx_canonical_facts_latest_seen
  ON canonical_facts(latest_seen);

CREATE TABLE IF NOT EXISTS service_contacts (
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

CREATE TABLE IF NOT EXISTS process_info (
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

CREATE TABLE IF NOT EXISTS facility_info (
  fact_id TEXT PRIMARY KEY,
  facility_name TEXT NOT NULL,
  info_type TEXT NOT NULL,
  location_hint TEXT,
  availability TEXT,
  rules_or_steps_json TEXT,
  caveats TEXT,
  FOREIGN KEY (fact_id) REFERENCES canonical_facts(fact_id)
);

CREATE TABLE IF NOT EXISTS fact_evidence (
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

CREATE INDEX IF NOT EXISTS idx_fact_evidence_fact_id
  ON fact_evidence(fact_id);

CREATE INDEX IF NOT EXISTS idx_fact_evidence_message_id
  ON fact_evidence(message_id);
