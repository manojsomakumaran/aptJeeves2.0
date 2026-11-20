from __future__ import annotations

import json
import sqlite3
from collections import Counter


class PiiVault:
    """Local store of original phone/email values behind redaction placeholders.

    Values are written at ingestion and read only to restore *service-contact*
    details into final answers. They must never reach an LLM or an event log.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def store(self, message_id: str, values: dict[str, str]) -> None:
        """Remember placeholder->value pairs for a message (idempotent)."""

        for placeholder, value in values.items():
            kind = placeholder.rsplit("_", 1)[0]
            self.connection.execute(
                "INSERT OR IGNORE INTO message_pii (message_id, placeholder, kind, value) VALUES (?, ?, ?, ?)",
                (message_id, placeholder, kind, value),
            )

    def resolve_service_contact(self, fact_id: str) -> int:
        """Fill in real values for a public service contact's placeholders.

        Only runs for facts that are public to residents and not resident
        affiliated. Placeholders are numbered per message, so the value is taken
        from the fact's evidence messages: the most common one wins, and a tie
        leaves the method unresolved rather than risk showing a wrong number.
        Returns the number of methods resolved.
        """

        row = self.connection.execute(
            """
            SELECT cf.privacy_status, sc.contact_methods_json, sc.is_resident_affiliated
            FROM canonical_facts cf JOIN service_contacts sc ON sc.fact_id = cf.fact_id
            WHERE cf.fact_id = ?
            """,
            (fact_id,),
        ).fetchone()
        if row is None or row["privacy_status"] != "public_to_residents" or row["is_resident_affiliated"]:
            return 0
        try:
            methods = json.loads(row["contact_methods_json"] or "[]")
        except ValueError:
            return 0
        if not isinstance(methods, list):
            return 0

        message_ids = [
            r["message_id"]
            for r in self.connection.execute("SELECT message_id FROM fact_evidence WHERE fact_id = ?", (fact_id,))
        ]
        resolved = 0
        for method in methods:
            if not isinstance(method, dict):
                continue
            placeholder = method.get("value_placeholder")
            if method.get("value") or not placeholder or not message_ids:
                continue
            marks = ",".join("?" * len(message_ids))
            found = Counter(
                r["value"]
                for r in self.connection.execute(
                    f"SELECT value FROM message_pii WHERE placeholder = ? AND message_id IN ({marks})",
                    (placeholder, *message_ids),
                )
            )
            top = found.most_common(2)
            if not top or (len(top) > 1 and top[0][1] == top[1][1]):
                continue
            method["value"] = top[0][0]
            resolved += 1
        if resolved:
            self.connection.execute(
                "UPDATE service_contacts SET contact_methods_json = ? WHERE fact_id = ?",
                (json.dumps(methods), fact_id),
            )
        return resolved

    def backfill_service_contacts(self) -> int:
        """Resolve every public service contact still holding bare placeholders."""

        total = 0
        for r in self.connection.execute(
            "SELECT fact_id FROM service_contacts WHERE contact_methods_json LIKE '%value_placeholder%'"
        ).fetchall():
            total += self.resolve_service_contact(r["fact_id"])
        return total
