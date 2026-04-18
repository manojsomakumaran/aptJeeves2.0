from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from aptjeeves.config import load_settings, resolve_db_path
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.storage.db import apply_migrations, connect
from aptjeeves.storage.repositories import ImportRunRepository


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for AptJeeves local operations."""

    parser = argparse.ArgumentParser(prog="aptjeeves")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path. Defaults to APTJEEVES_DB_PATH or aptjeeves.sqlite3.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest a chat export.")
    ingest.add_argument("--platform", required=True, choices=["whatsapp", "telegram"])
    ingest.add_argument("--file", required=True, type=Path)
    ingest.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name. Selects data/apartments/<slug>/aptjeeves.sqlite3.",
    )
    ingest.add_argument(
        "--chat-name",
        default=None,
        help=(
            "Stable chat/channel name inside the apartment. If omitted, AptJeeves "
            "infers it from the export filename."
        ),
    )
    ingest.add_argument("--timezone", default=None)
    ingest.add_argument("--date-order", default="DMY", choices=["DMY", "MDY"])

    status = subparsers.add_parser("import-status", help="Show an import summary.")
    status.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    status.add_argument("--batch", required=True)

    extract = subparsers.add_parser(
        "extract-pending",
        help="Extract canonical facts from pending raw messages using the fake extractor.",
    )
    extract.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    extract.add_argument("--limit", type=int, default=100)

    index = subparsers.add_parser(
        "index-facts",
        help="Create or refresh vector entries for canonical facts.",
    )
    index.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    index.add_argument("--limit", type=int, default=100)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the AptJeeves CLI and return a process exit code."""

    args = build_parser().parse_args(argv)
    settings = load_settings()
    db_path = resolve_db_path(
        settings=settings,
        explicit_db_path=args.db,
        apartment=getattr(args, "apartment", None),
    )

    # Every command opens the local DB and applies migrations first so a fresh
    # checkout can run `aptjeeves ingest` without a separate setup command.
    connection = connect(db_path)
    apply_migrations(connection)

    if args.command == "ingest":
        chat_name = args.chat_name
        if chat_name is None and args.platform == "whatsapp":
            chat_name = infer_chat_name_from_file(args.file)
        # Print machine-readable JSON so scripts can capture import_batch_id and
        # use it with future status/replay commands.
        service = ChatIngestionService(connection)
        summary = service.ingest(
            IngestRequest(
                platform=args.platform,
                file_path=args.file,
                chat_name=chat_name,
                default_timezone=args.timezone or settings.default_timezone,
                date_order=args.date_order,
            )
        )
        print(
            json.dumps(
                {
                    "import_batch_id": summary.import_batch_id,
                    "status": summary.status,
                    "total_messages_seen": summary.total_messages_seen,
                    "new_messages_inserted": summary.new_messages_inserted,
                    "duplicate_messages_skipped": summary.duplicate_messages_skipped,
                    "parse_failures": summary.parse_failures,
                    "db_path": str(db_path),
                    "chat_name": summary.chat_name,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "import-status":
        # Status reads the import_runs summary rather than replaying event logs.
        repo = ImportRunRepository(connection)
        summary = repo.get_summary(args.batch)
        if summary is None:
            print(f"Import batch not found: {args.batch}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "import_batch_id": summary.import_batch_id,
                    "status": summary.status,
                    "total_messages_seen": summary.total_messages_seen,
                    "new_messages_inserted": summary.new_messages_inserted,
                    "duplicate_messages_skipped": summary.duplicate_messages_skipped,
                    "parse_failures": summary.parse_failures,
                    "db_path": str(db_path),
                    "chat_name": summary.chat_name,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "extract-pending":
        service = ExtractionService(connection, FakeExtractor())
        fact_ids = service.extract_pending(limit=args.limit)
        print(
            json.dumps(
                {
                    "status": "completed",
                    "facts_upserted": len(fact_ids),
                    "fact_ids": fact_ids,
                    "db_path": str(db_path),
                    "extractor": "fake",
                },
                indent=2,
            )
        )
        return 0

    if args.command == "index-facts":
        service = VectorIndexingService(connection)
        vector_ids = service.index_pending(limit=args.limit)
        print(
            json.dumps(
                {
                    "status": "completed",
                    "vectors_upserted": len(vector_ids),
                    "vector_ids": vector_ids,
                    "db_path": str(db_path),
                    "embedding_model": service.embedding_model.model_version,
                },
                indent=2,
            )
        )
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


def infer_chat_name_from_file(file_path: Path) -> str:
    """Infer a stable chat/channel name from a chat export filename.

    WhatsApp text exports usually do not contain a reliable group name inside
    the file content. The best no-input default is therefore the filename, with
    common export prefixes removed. Users can still pass `--chat-name` when a
    monthly export filename includes dates or other changing text.
    """

    stem = file_path.stem.strip()
    stem = re.sub(r"^WhatsApp Chat with\s+", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"^Telegram Chat with\s+", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        raise ValueError(f"Could not infer chat name from file path: {file_path}")
    return stem


if __name__ == "__main__":
    raise SystemExit(main())
