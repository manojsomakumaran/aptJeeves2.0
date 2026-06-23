from __future__ import annotations

import logging
import shutil
import tempfile
import copy
from pathlib import Path
from typing import Any

from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langfuse.decorators import observe, langfuse_context

from aptjeeves.config import load_settings, resolve_db_path, Settings
from aptjeeves.storage.db import connect, apply_migrations
from aptjeeves.storage.repositories import RawMessageRepository, CanonicalFactRepository, VectorEntryRepository
from aptjeeves.cli import _build_extractor, _build_embedding_model, _build_answerer, _build_intent_classifier
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.retrieval.service import QueryService
from aptjeeves.answering.formatter import AnswerFormatter

logger = logging.getLogger(__name__)
# API Server Entrypoint
# (Forced save to disk)

app = FastAPI(title="AptJeeves 2.0 API")

# Allow React frontend to communicate with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://your-production-domain.com"],  # In production, restrict this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Dependencies ---

def get_settings() -> Settings:
    return load_settings()

def get_db_connection(apartment: str, settings: Settings = Depends(get_settings)):
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    apply_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


# --- Models ---

class AskRequest(BaseModel):
    query: str
    top_k: int = 10
    max_facts: int = 5

class ActionResponse(BaseModel):
    status: str
    message: str
    details: dict[str, Any] = {}

class ApartmentSettingsUpdate(BaseModel):
    embedding_model: str | None = None
    extraction_model: str | None = None

def get_apartment_local_settings(conn) -> dict:
    conn.execute("CREATE TABLE IF NOT EXISTS apartment_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    rows = conn.execute("SELECT key, value FROM apartment_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}

def _apply_local_settings(conn, settings: Settings) -> Settings:
    local_settings = get_apartment_local_settings(conn)
    new_settings = copy.copy(settings)
    if "embedding_model" in local_settings:
        new_settings.embedding_model = local_settings["embedding_model"]
    if "extraction_model" in local_settings:
        new_settings.extraction_model = local_settings["extraction_model"]
    return new_settings

# --- Routes: Chat & Query ---

@app.post("/api/{apartment}/ask")
@observe(name="api_ask_question")
def ask_question(apartment: str, req: AskRequest, settings: Settings = Depends(get_settings)):
    """Ask a question to the AptJeeves AI for a specific apartment."""
    langfuse_context.update_current_trace(
        session_id=apartment,
    )
    
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    apply_migrations(conn)
    
    try:
        local_settings = _apply_local_settings(conn, settings)
        service = QueryService(
            conn,
            embedding_model=_build_embedding_model(local_settings),
            answerer=_build_answerer(local_settings),
            intent_classifier=_build_intent_classifier(local_settings),
            top_k=req.top_k,
            max_answer_facts=req.max_facts,
        )
        answer = service.ask(req.query)
        return AnswerFormatter().to_json(answer)
    except Exception as e:
        logger.error(f"Error answering query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# --- Routes: Data Processing & Advanced Settings ---

@app.get("/api/apartments")
def list_apartments(settings: Settings = Depends(get_settings)):
    """Dynamically fetch the list of available apartment databases."""
    apartments_dir = Path(settings.data_dir) / "apartments"
    apartments = []
    if apartments_dir.exists() and apartments_dir.is_dir():
        for entry in apartments_dir.iterdir():
            if entry.is_dir() and (entry / "aptjeeves.sqlite3").exists():
                apartments.append(entry.name)
    return {"apartments": apartments}


@app.get("/api/{apartment}/status")
def get_processing_status(apartment: str, settings: Settings = Depends(get_settings)):
    """Fetch the current counts for the UI progress bars and advanced settings."""
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    try:
        raw_repo = RawMessageRepository(conn)
        fact_repo = CanonicalFactRepository(conn)
        vector_repo = VectorEntryRepository(conn)
        
        # Fetch recent imports from the database
        recent_imports = conn.execute(
            "SELECT import_batch_id, started_at, source_platform, new_messages_inserted FROM import_runs ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
        
        history = []
        for row in recent_imports:
            history.append({
                "date": row["started_at"][:10],
                "batch_id": row["import_batch_id"][:10] + "...",
                "platform": row["source_platform"],
                "messages": row["new_messages_inserted"],
            })

        local_settings_dict = get_apartment_local_settings(conn)
        current_embedding_model = local_settings_dict.get("embedding_model", settings.embedding_model)
        current_extraction_model = local_settings_dict.get("extraction_model", settings.extraction_model)

        return {
            "messages": {
                "total_new": raw_repo.count_by_processing_status("new"),
                "total_failed": raw_repo.count_by_processing_status("failed"),
                "total_extracted": raw_repo.count_by_processing_status("extracted"),
            },
            "facts": {
                "total": fact_repo.connection.execute("SELECT COUNT(*) as count FROM canonical_facts").fetchone()["count"],
                "pending_indexing": fact_repo.count_facts_for_indexing(embedding_model_version=current_embedding_model)
            },
            "vectors": {
                "active": vector_repo.count_active(embedding_model_version=current_embedding_model)
            },
            "current_models": {
                "extraction": current_extraction_model,
                "embedding": current_embedding_model
            },
            "history": history
        }
    finally:
        conn.close()


@app.get("/api/{apartment}/settings")
def get_apartment_settings(apartment: str, settings: Settings = Depends(get_settings)):
    """Fetch per-apartment configuration settings."""
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    apply_migrations(conn)
    try:
        local_settings = get_apartment_local_settings(conn)
        return {
            "embedding_model": local_settings.get("embedding_model", settings.embedding_model),
            "extraction_model": local_settings.get("extraction_model", settings.extraction_model)
        }
    finally:
        conn.close()


@app.post("/api/{apartment}/settings", response_model=ActionResponse)
def update_apartment_settings(apartment: str, req: ApartmentSettingsUpdate, settings: Settings = Depends(get_settings)):
    """Update per-apartment configuration settings."""
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    apply_migrations(conn)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS apartment_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        with conn:
            if req.embedding_model is not None:
                conn.execute("INSERT OR REPLACE INTO apartment_settings (key, value) VALUES (?, ?)", ("embedding_model", req.embedding_model))
            if req.extraction_model is not None:
                conn.execute("INSERT OR REPLACE INTO apartment_settings (key, value) VALUES (?, ?)", ("extraction_model", req.extraction_model))
        return ActionResponse(status="success", message="Apartment settings updated.")
    finally:
        conn.close()


@app.post("/api/{apartment}/reset-failed", response_model=ActionResponse)
def reset_failed_messages(apartment: str, settings: Settings = Depends(get_settings)):
    """Reset failed raw messages back to 'new' (Satisfies Requirement #3)."""
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    apply_migrations(conn)
    try:
        repo = RawMessageRepository(conn)
        with conn:
            count = repo.reset_failed()
        return ActionResponse(status="success", message=f"Reset {count} failed messages.", details={"count": count})
    finally:
        conn.close()


@app.post("/api/{apartment}/upload", response_model=ActionResponse)
async def upload_chat_export(
    apartment: str,
    background_tasks: BackgroundTasks,
    platform: str = Form(...),
    primary_filename: str = Form(...),
    files: list[UploadFile] = File(...),
    attachment_folder: str | None = Form(None),
    settings: Settings = Depends(get_settings)
):
    """Receive a folder/list of chat exports and trigger ingestion, extraction, and indexing."""
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    
    temp_dir = Path(tempfile.mkdtemp())
    primary_file_path = None
    
    try:
        if attachment_folder:
            att_path = Path(attachment_folder)
            if not att_path.exists() or not att_path.is_dir():
                raise HTTPException(status_code=400, detail=f"Attachment folder '{attachment_folder}' is not accessible or not a directory.")

        for file in files:
            # Using the basename (.name) isolates files locally without trusting potential path traversal
            file_path = temp_dir / Path(file.filename).name
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
            if Path(file.filename).name == primary_filename:
                primary_file_path = file_path
                
        if not primary_file_path:
            raise HTTPException(status_code=400, detail=f"Primary file '{primary_filename}' not found in uploaded folder.")
            
        conn = connect(db_path)
        apply_migrations(conn)
        try:
            service = ChatIngestionService(conn)
            summary = service.ingest(
                IngestRequest(platform=platform.lower(), file_path=primary_file_path, default_timezone=settings.default_timezone)
            )
            
            # Automatically trigger extraction and indexing in the background
            background_tasks.add_task(run_extraction_task, db_path, settings, 100)
            background_tasks.add_task(run_indexing_task, db_path, settings, 100)
            
            return ActionResponse(
                status="success", 
                message=f"Ingested {summary.new_messages_inserted} new messages. Pipeline tasks started.", 
                details={"batch_id": summary.import_batch_id}
            )
        except Exception as e:
            logger.error(f"Ingestion failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.get("/api/{apartment}/observability")
def get_observability_stats(apartment: str, settings: Settings = Depends(get_settings)):
    """Fetch real OpenAI token usage, estimated costs, and latency metrics."""
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    apply_migrations(conn)
    try:
        # Check if llm_calls table exists first
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_calls'"
        ).fetchone()
        
        if table_exists:
            # Aggregate Total Tokens and Cost
            usage_row = conn.execute(
                "SELECT SUM(input_tokens + output_tokens) as total_tokens, SUM(CAST(estimated_cost AS REAL)) as total_cost FROM llm_calls"
            ).fetchone()
            
            # Aggregate Average Latencies per operation type
            latency_rows = conn.execute(
                "SELECT purpose, AVG(latency_ms) as avg_latency FROM llm_calls GROUP BY purpose"
            ).fetchall()
        else:
            usage_row = {"total_tokens": 0, "total_cost": 0.0}
            latency_rows = []
        
        return {
            "usage": {
                "total_tokens": usage_row["total_tokens"] or 0,
                "total_cost": usage_row["total_cost"] or 0.0
            },
            "latencies": {row["purpose"]: round(row["avg_latency"] or 0, 2) for row in latency_rows}
        }
    finally:
        conn.close()


@app.get("/api/{apartment}/logs")
def get_recent_logs(apartment: str, limit: int = 100, settings: Settings = Depends(get_settings)):
    """Fetch recent pipeline events for the logs viewer."""
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    conn = connect(db_path)
    apply_migrations(conn)
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pipeline_events'"
        ).fetchone()
        
        if not table_exists:
            return {"events": []}
            
        rows = conn.execute(
            "SELECT timestamp, event_type, status, details FROM pipeline_events ORDER BY timestamp DESC LIMIT ?", 
            (limit,)
        ).fetchall()
        
        events = []
        for row in rows:
            event = dict(row)
            events.append(event)
            
        return {"events": events}
    finally:
        conn.close()

# --- Routes: Background Tasks (Extraction & Indexing) ---

def run_extraction_task(db_path: Path, settings: Settings, limit: int = 100):
    """Background task to process the extraction queue."""
    conn = connect(db_path)
    events = ObservabilityService(conn)
    trace_id = f"trace_bg_extract_{uuid.uuid4().hex}"
    try:
        events.emit(trace_id=trace_id, event_type="background_task_started", stage="extraction", payload={"task": "run_extraction_task", "limit": limit})
        local_settings = _apply_local_settings(conn, settings)
        extractor = _build_extractor(local_settings)
        service = ExtractionService(conn, extractor)
        summary = service.extract_pending(limit=limit)
        events.emit(trace_id=trace_id, event_type="background_task_completed", stage="extraction", status="success", payload={"task": "run_extraction_task", "facts_extracted": len(summary.fact_ids)})
    except Exception as e:
        logger.error(f"Background extraction task failed: {e}", exc_info=True)
        events.emit(trace_id=trace_id, event_type="background_task_failed", stage="extraction", status="error", payload={"task": "run_extraction_task", "error": str(e)})
    finally:
        conn.close()

@app.post("/api/{apartment}/extract", response_model=ActionResponse)
def trigger_extraction(apartment: str, background_tasks: BackgroundTasks, settings: Settings = Depends(get_settings)):
    """Start a background job to extract facts from pending messages."""
    import uuid
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    background_tasks.add_task(run_extraction_task, db_path, settings, 100)
    return ActionResponse(status="success", message="Extraction background task started.")


def run_indexing_task(db_path: Path, settings: Settings, limit: int = 100):
    """Background task to process the indexing queue."""
    import uuid
    conn = connect(db_path)
    events = ObservabilityService(conn)
    trace_id = f"trace_bg_index_{uuid.uuid4().hex}"
    try:
        events.emit(trace_id=trace_id, event_type="background_task_started", stage="indexing", payload={"task": "run_indexing_task", "limit": limit})
        local_settings = _apply_local_settings(conn, settings)
        embedding_model = _build_embedding_model(local_settings)
        service = VectorIndexingService(conn, embedding_model)
        summary = service.index_pending(limit=limit)
        events.emit(trace_id=trace_id, event_type="background_task_completed", stage="indexing", status="success", payload={"task": "run_indexing_task", "vectors_upserted": summary.vectors_upserted})
    except Exception as e:
        logger.error(f"Background indexing task failed: {e}", exc_info=True)
        events.emit(trace_id=trace_id, event_type="background_task_failed", stage="indexing", status="error", payload={"task": "run_indexing_task", "error": str(e)})
    finally:
        conn.close()

@app.post("/api/{apartment}/index", response_model=ActionResponse)
def trigger_indexing(apartment: str, background_tasks: BackgroundTasks, settings: Settings = Depends(get_settings)):
    """Start a background job to index pending facts."""
    import uuid
    db_path = resolve_db_path(settings=settings, explicit_db_path=None, apartment=apartment)
    background_tasks.add_task(run_indexing_task, db_path, settings, 100)
    return ActionResponse(status="success", message="Indexing background task started.")