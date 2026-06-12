# AptJeeves 2.0 UI Implementation Plan

This document outlines the comprehensive plan for designing and implementing the React-based Graphical User Interface (GUI) for AptJeeves 2.0.

## 1. Technology Stack
*   **Framework:** React with TypeScript, bundled via Vite.
*   **Routing:** React Router (handling Chat, Ingestion/Tasks, Stats, Usage, and Logs pages).
*   **State Management & Data Fetching:** React Query (TanStack Query) for polling background tasks and caching API responses.
*   **Styling & UI Components:** Tailwind CSS combined with `shadcn/ui` (or Radix UI) for accessible, clean components.

## 2. Application Layout
The application will feature a **persistent sidebar** for navigation between the different functional pages. The context of the active "Apartment" will be managed locally on the relevant pages to allow multitasking (e.g., querying one apartment while ingesting data for another).

## 3. Phased Implementation Strategy

### Phase 1: Backend API Readiness & Testing
*   **Goal:** Ensure the FastAPI backend (`server.py`) supports all UI features and is fully tested against regressions.
*   **Tasks:**
    *   **Update `/upload`:** Modify the endpoint to accept a list of files (`files: list[UploadFile]`) representing a folder upload, along with a `primary_filename` form field. Attach FastAPI `BackgroundTasks` to automatically trigger `run_extraction_task` and `run_indexing_task` after ingestion.
    *   **Add `/settings` Endpoints:** Create `GET /api/{apartment}/settings` and `POST /api/{apartment}/settings` to manage per-apartment configurations (like the embedding model).
    *   **Add `/apartments` Endpoint:** Create an endpoint to dynamically fetch the list of available apartment databases.
    *   **Automated Testing:** Write `pytest` functions for the new `/upload`, `/settings`, and `/apartments` endpoints, and verify schema returns for `/status` and `/observability`.

### Phase 2: Frontend Initialization & Layout
*   **Goal:** Bootstrap the Single Page Application (SPA) and establish the core routing/layout.
*   **Tasks:**
    *   Scaffold the project using Vite + React + TypeScript.
    *   Install and configure Tailwind CSS and standard UI components.
    *   Set up React Router for navigation (Chat, Ingestion, Stats, Usage, Logs).
    *   Configure `React Query` for data fetching.
    *   Build the persistent sidebar layout.

### Phase 3: Global Context & Chat Interface
*   **Goal:** Implement the primary resident-facing query functionality.
*   **Tasks:**
    *   Build the "Apartment Selector" dropdown to set the context for the chat.
    *   Build the Chat UI (message bubbles, input area, "Ask" button).
    *   Wire up the `/api/{apartment}/ask` endpoint.
    *   Implement the expandable "Citations" component beneath the AI's summary answers.

### Phase 4: Folder Ingestion & Task Manager
*   **Goal:** Build the unified upload and background tracking experience.
*   **Tasks:**
    *   Implement the Folder Selection component (using HTML5 `<input webkitdirectory />`).
    *   Add logic to parse the selected folder tree, locate `.txt`/`.json` chat exports, and let the user specify the primary chat file.
    *   Wire the upload form to the updated `/upload` API.
    *   Build the Task Manager list that polls `/api/{apartment}/status` to display background progress (Ingestion -> Extraction -> Indexing).

### Phase 5: Statistics & Observability Dashboards
*   **Goal:** Visualize the health, usage, and cost of the system.
*   **Tasks:**
    *   **System Statistics:** Display overall progress (Total New, Extracted, Failed messages, Active Vectors) from `/status`.
    *   **Usage & Billing:** Visualize token usage, estimated costs, and latencies from `/observability`.

### Phase 6: Advanced Settings, Error Recovery, & Logs
*   **Goal:** Provide management, deep debugging capabilities, and cost-saving error recovery.
*   **Tasks:**
    *   **Advanced Settings Modal:** Build a UI to change settings like the embedding model per apartment via the `/settings` endpoint.
    *   **Reset Failed State (Error Recovery):** Add an advanced option to trigger the `/reset-failed` endpoint. If the extraction or indexing phase encounters errors and raw messages are marked as `failed`, this option allows resetting their status back to `new`. This ensures only the failed lines are re-processed by the background tasks, preventing wasteful re-extraction of successful entries and saving OpenAI API credits.
    *   **Logs Viewer:** Create a page to display backend SQLite events and provide integrated Langfuse tracing links for LLM calls.