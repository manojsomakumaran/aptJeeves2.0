from __future__ import annotations

import json
import sqlite3


# OpenAI embedding models reject inputs over 8192 tokens. Token-dense text
# (phone numbers, Indic scripts, tables) can approach 1 token per character, so
# the caps are character-based and conservative.
MAX_SNIPPET_CHARS = 800
MAX_EMBEDDING_CHARS = 6000


class EmbeddingTextBuilder:
    """Build sanitized retrieval text for canonical facts."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Create a builder bound to the canonical SQLite store."""

        self.connection = connection

    def build(self, fact: sqlite3.Row) -> str:
        """Return embedding text for a canonical fact row."""

        fact_type = fact["fact_type"]
        if fact_type == "service_contact":
            text = self._service_contact_text(fact)
        elif fact_type == "process_info":
            text = self._process_info_text(fact)
        elif fact_type == "facility_info":
            text = self._facility_info_text(fact)
        else:
            text = self._base_text(fact)
        return text[:MAX_EMBEDDING_CHARS]

    def _base_text(self, fact: sqlite3.Row) -> str:
        """Return fields shared by all fact types."""

        return "\n".join(
            [
                f"Fact type: {fact['fact_type']}",
                f"Title: {fact['title']}",
                f"Summary: {fact['summary']}",
                f"Privacy status: {fact['privacy_status']}",
                f"Source count: {fact['source_count']}",
                f"Latest seen: {fact['latest_seen']}",
                f"Confidence: {fact['confidence']}",
            ]
        )

    def _service_contact_text(self, fact: sqlite3.Row) -> str:
        details = self.connection.execute(
            "SELECT * FROM service_contacts WHERE fact_id = ?",
            (fact["fact_id"],),
        ).fetchone()
        parts = [self._base_text(fact)]
        if details is not None:
            parts.extend(
                [
                    f"Service type: {details['service_type']}",
                    f"Display name: {details['display_name'] or ''}",
                    f"Contact classification: {details['contact_classification']}",
                    f"Area or scope: {details['area_or_scope'] or ''}",
                    f"Price hint: {details['price_hint'] or ''}",
                    f"Availability hint: {details['availability_hint'] or ''}",
                    f"Caveats: {details['caveats'] or ''}",
                ]
            )
        parts.append(self._evidence_text(fact["fact_id"]))
        return "\n".join(part for part in parts if part.strip())

    def _process_info_text(self, fact: sqlite3.Row) -> str:
        details = self.connection.execute(
            "SELECT * FROM process_info WHERE fact_id = ?",
            (fact["fact_id"],),
        ).fetchone()
        parts = [self._base_text(fact)]
        if details is not None:
            parts.extend(
                [
                    f"Process: {details['process_name']}",
                    f"Category: {details['category'] or ''}",
                    f"Authority/provider: {details['provider_or_authority'] or ''}",
                    f"Steps: {_json_list_text(details['steps_json'])}",
                    f"Documents: {_json_list_text(details['required_documents_json'])}",
                    f"Fees: {_json_list_text(details['fees_json'])}",
                    f"Locations or portals: {_json_list_text(details['locations_or_portals_json'])}",
                    f"Deadlines: {_json_list_text(details['deadlines_json'])}",
                    f"Caveats: {details['caveats'] or ''}",
                    f"Staleness risk: {details['staleness_risk']}",
                ]
            )
        parts.append(self._evidence_text(fact["fact_id"]))
        return "\n".join(part for part in parts if part.strip())

    def _facility_info_text(self, fact: sqlite3.Row) -> str:
        details = self.connection.execute(
            "SELECT * FROM facility_info WHERE fact_id = ?",
            (fact["fact_id"],),
        ).fetchone()
        parts = [self._base_text(fact)]
        if details is not None:
            parts.extend(
                [
                    f"Facility: {details['facility_name']}",
                    f"Info type: {details['info_type']}",
                    f"Location hint: {details['location_hint'] or ''}",
                    f"Availability: {details['availability'] or ''}",
                    f"Rules or steps: {_json_list_text(details['rules_or_steps_json'])}",
                    f"Caveats: {details['caveats'] or ''}",
                ]
            )
        parts.append(self._evidence_text(fact["fact_id"]))
        return "\n".join(part for part in parts if part.strip())

    def _evidence_text(self, fact_id: str) -> str:
        """Return sanitized evidence snippets for retrieval context."""

        rows = self.connection.execute(
            """
            SELECT sanitized_snippet
            FROM fact_evidence
            WHERE fact_id = ?
            ORDER BY created_at, evidence_id
            LIMIT 5
            """,
            (fact_id,),
        ).fetchall()
        snippets = [row["sanitized_snippet"][:MAX_SNIPPET_CHARS] for row in rows]
        if not snippets:
            return ""
        return "Evidence snippets: " + " | ".join(snippets)


def _json_list_text(value: str | None) -> str:
    """Render a JSON list column as text for embedding."""

    if not value:
        return ""
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        return ""
    return "; ".join(str(item) for item in parsed)
