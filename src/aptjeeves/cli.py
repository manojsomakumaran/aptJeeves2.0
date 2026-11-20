from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from aptjeeves.attachments.repository import AttachmentRepository
from aptjeeves.attachments.service import AttachmentService
from aptjeeves.config import Settings, load_settings, resolve_db_path
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.observability.replay import ReplayService
from aptjeeves.retrieval.service import QueryService
from aptjeeves.storage.db import apply_migrations, connect
from aptjeeves.storage.repositories import ImportRunRepository, QueryRunRepository, RawMessageRepository
from aptjeeves.builders import build_embedding_model, build_answerer, build_extractor, build_intent_classifier
from aptjeeves.answering.formatter import AnswerFormatter


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
    ingest.add_argument("--date-order", default="AUTO", choices=["AUTO", "DMY", "MDY"])
    ingest.add_argument(
        "--upload-dir",
        default=None,
        type=Path,
        help=(
            "Directory containing attachments referenced by the export "
            "(.vcf contacts plus PDF/DOCX/XLSX/CSV/TXT documents)."
        ),
    )

    status = subparsers.add_parser("import-status", help="Show an import summary.")
    status.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    status.add_argument("--batch", required=True)

    query_status = subparsers.add_parser("query-status", help="Show a query summary.")
    query_status.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    query_status.add_argument("--query-id", required=True)

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

    process_attachments = subparsers.add_parser(
        "process-attachments",
        help="Extract text from pending attachments and queue the segments for extraction.",
    )
    process_attachments.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    process_attachments.add_argument("--limit", type=int, default=50)

    reset_failed = subparsers.add_parser(
        "reset-failed",
        help="Reset all 'failed' raw messages and attachments for another attempt.",
    )
    reset_failed.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )

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

    ask_parser = subparsers.add_parser("ask", help="Ask a question about the apartment community.")
    ask_parser.add_argument("query", help="The resident question to answer.")
    ask_parser.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    ask_parser.add_argument("--top-k", type=int, default=10, help="Maximum retrieval candidates.")
    ask_parser.add_argument("--max-facts", type=int, default=5, help="Maximum facts in the answer.")

    replay_import = subparsers.add_parser("replay-import", help="Replay extraction and indexing for an import batch.")
    replay_import.add_argument("--batch", required=True)
    replay_import.add_argument("--from-stage", required=True, choices=["extraction"])
    replay_import.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )

    replay_fact = subparsers.add_parser("replay-fact-index", help="Replay indexing for one fact.")
    replay_fact.add_argument("--fact", required=True)
    replay_fact.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )

    replay_query = subparsers.add_parser("replay-query", help="Replay one query from stored redacted text.")
    replay_query.add_argument("--query-id", required=True)
    replay_query.add_argument(
        "--apartment",
        default=None,
        help="Apartment chatbot name used to select the database.",
    )
    replay_query.add_argument("--top-k", type=int, default=10, help="Maximum retrieval candidates.")
    replay_query.add_argument("--max-facts", type=int, default=5, help="Maximum facts in the answer.")

    show_events = subparsers.add_parser("show-events", help="Show recent pipeline events from the database.")
    show_events.add_argument(
        "--apartment",
        required=True,
        help="Apartment chatbot name used to select the database.",
    )
    show_events.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of recent events to show.",
    )
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
                upload_dir=args.upload_dir,
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

    if args.command == "query-status":
        repo = QueryRunRepository(connection)
        summary = repo.get_summary(args.query_id)
        if summary is None:
            print(f"Query not found: {args.query_id}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "query_id": summary.query_id,
                    "status": summary.status,
                    "query_text_redacted": summary.query_text_redacted,
                    "query_intent": summary.query_intent,
                    "final_action": summary.final_action,
                    "retrieval_trace_id": summary.retrieval_trace_id,
                    "guardrail_events_count": summary.guardrail_events_count,
                    "created_at": summary.created_at,
                    "completed_at": summary.completed_at,
                    "db_path": str(db_path),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "reset-failed":
        repo = RawMessageRepository(connection)
        with connection:
            count = repo.reset_failed()
            attachments_reset = AttachmentRepository(connection).reset_failed()

        if attachments_reset > 0:
            print(
                f"Reset {attachments_reset} failed attachments back to 'pending'. "
                "Run process-attachments to retry them.",
                file=sys.stderr,
            )
        if count > 0:
            print(f"Reset {count} failed messages back to 'new'. You can now run extract-pending.", file=sys.stderr)
        else:
            print("No failed messages found.", file=sys.stderr)

        print(
            json.dumps(
                {
                    "status": "completed",
                    "messages_reset": count,
                    "attachments_reset": attachments_reset,
                    "db_path": str(db_path),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "process-attachments":
        service = AttachmentService(connection)
        summary = service.process_pending(limit=args.limit)
        print(
            json.dumps(
                {
                    "status": "completed",
                    "processed": summary.processed,
                    "text_extracted": summary.text_extracted,
                    "segments_inserted": summary.segments_inserted,
                    "no_text": summary.no_text,
                    "skipped_sensitive": summary.skipped_sensitive,
                    "failed": summary.failed,
                    "remaining_pending": summary.remaining_pending,
                    "attachment_status_counts": service.attachments.count_by_status(),
                    "db_path": str(db_path),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "extract-pending":
        extractor = build_extractor(settings)
        service = ExtractionService(connection, extractor)
        summary = service.extract_pending(limit=args.limit)
        print(
            json.dumps(
                {
                    "status": "completed",
                    "facts_upserted": len(summary.fact_ids),
                    "extraction_failures": summary.extraction_failures,
                    "fact_ids": summary.fact_ids,
                    "db_path": str(db_path),
                    "extractor": settings.extraction_backend if settings.extraction_backend in ("fake", "openai") else "fake",
                },
                indent=2,
            )
        )
        return 0

    if args.command == "index-facts":
        embedding_model = build_embedding_model(settings)
        service = VectorIndexingService(connection, embedding_model)
        summary = service.index_pending(limit=args.limit)

        if summary.remaining_pending > 0:
            print(f"Indexed {summary.total_pending_before - summary.remaining_pending} facts. {summary.remaining_pending} facts remaining (approx. {summary.estimated_batches_remaining} runs left).", file=sys.stderr)
        else:
            print("Vector indexing backlog cleared.", file=sys.stderr)

        print(
            json.dumps(
                {
                    "status": "completed",
                    "vectors_upserted": len(summary.vector_ids),
                    "total_pending_before": summary.total_pending_before,
                    "remaining_pending": summary.remaining_pending,
                    "estimated_batches_remaining": summary.estimated_batches_remaining,
                    "limit_applied": summary.limit_applied,
                    "vector_ids": summary.vector_ids,
                    "db_path": str(db_path),
                    "embedding_model": service.embedding_model.model_version,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "ask":
        embedding_model = build_embedding_model(settings)
        answerer = build_answerer(settings)
        service = QueryService(
            connection,
            embedding_model=embedding_model,
            answerer=answerer,
            intent_classifier=build_intent_classifier(settings),
            top_k=args.top_k,
            max_answer_facts=args.max_facts,
        )
        answer = service.ask(args.query)
        output = AnswerFormatter().to_json(answer)
        output["db_path"] = str(db_path)
        print(json.dumps(output, indent=2))
        return 0

    if args.command == "replay-import":
        replay = ReplayService(connection)
        result = replay.replay_import(
            import_batch_id=args.batch,
            extractor=build_extractor(settings),
            embedding_model=build_embedding_model(settings),
        )
        result["db_path"] = str(db_path)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "replay-fact-index":
        replay = ReplayService(connection)
        result = replay.replay_fact_index(
            fact_id=args.fact,
            embedding_model=build_embedding_model(settings),
        )
        result["db_path"] = str(db_path)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "replay-query":
        replay = ReplayService(connection)
        answer = replay.replay_query(
            query_id=args.query_id,
            embedding_model=build_embedding_model(settings),
            answerer=build_answerer(settings),
            intent_classifier=build_intent_classifier(settings),
            top_k=args.top_k,
            max_answer_facts=args.max_facts,
        )
        output = AnswerFormatter().to_json(answer)
        output["db_path"] = str(db_path)
        print(json.dumps(output, indent=2))
        return 0

    if args.command == "show-events":
        table_exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pipeline_events'"
        ).fetchone()
        if not table_exists:
            print(f"No 'pipeline_events' table found in {db_path}", file=sys.stderr)
            return 1

        cursor = connection.execute(
            "SELECT created_at, event_type, severity as status, stage, sanitized_payload_json as details FROM pipeline_events ORDER BY created_at DESC LIMIT ?",
            (args.limit,)
        )
        events = [dict(row) for row in cursor]

        if not events:
            print(f"No events found in {db_path}", file=sys.stderr)
            return 0

        print(json.dumps(events, indent=2))
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
