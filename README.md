# BA Agent — Phase 2

FastAPI/React modular monolith for versioned business requirement intake, remote
Ollama analysis, persisted customer clarification and draft JSON/Markdown summaries.
Phase 1 APIs remain available. No approvals, architecture agent, stories or tasks
are implemented. Ollama runs exclusively on your existing remote server.

## Remote Ollama setup

Preserve your existing `.env`. If starting fresh, copy `.env.example` once, then set:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://YOUR_SERVER_IP:11434
OLLAMA_MODEL=YOUR_AVAILABLE_MODEL
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_TEMPERATURE=0
OLLAMA_MAX_ATTEMPTS=3
OLLAMA_NUM_PREDICT=4096
OLLAMA_THINK=auto
CLARIFICATION_BATCH_SIZE=5
```

Use the remote server root or a reverse-proxy base prefix. Recognized copied native
endpoint suffixes such as `/api/tags` and `/api/chat` are normalized automatically.
Only existing models are used: no model pulls, local installation or Ollama container.
The server must support native `/api/tags` and `/api/chat` with JSON-schema `format`.
The exact model name/tag must appear in its model listing.

From the repository root after installing backend dependencies:

```powershell
.\backend\.venv\Scripts\python.exe -m app.check_ollama --env-file .env
# Optional: exercise the real analysis schema using synthetic customer text.
.\backend\.venv\Scripts\python.exe -m app.check_ollama --env-file .env --no-probe --analysis-probe
```

The dashboard's **Check remote model** action performs the same availability and
small schema probe. Connection/429/5xx failures retry at most three times;
generation read timeouts fail immediately without repeating potentially ongoing
remote work. `OLLAMA_THINK=low` reduces reasoning effort on models supporting that
level; `auto` preserves model defaults and `off` requests no thinking where supported.
The output budget is configurable through `OLLAMA_NUM_PREDICT` (default 4096).
Larger analyses may require a larger budget; incomplete output is rejected, never
silently accepted. Increasing the timeout permits a longer wait but does not speed up generation.

Answer updates are deterministic and make no model call. Original requirement
text/provenance is preserved. Every active confirmed answer becomes a separate,
stable decision requirement with the exact selected values and an answer source
reference. Editing or invalidating an answer replaces/removes the corresponding
decision while preserving history. Unchanged generic requirements never gain
customer-confirmed labels merely because a source reference was attached.

Initial extraction is followed by an independent, structured source-support review.
Unsupported elaborations such as assumed CRUD privileges are separated as assumptions.
This is a model-assisted quality check, not proof of semantic correctness or approval;
customer review remains necessary. The working description includes actual decisions,
gap resolution status and an explicit list of remaining blockers. TBD/unknown answers
are saved but do not resolve a blocking question.
invalid JSON, missing fields, incomplete generations and compatibility errors
fail explicitly. Responses omit remote error bodies and credentials. Usage tracks
input/output tokens, wall latency including network retries and attempt count.
Failed calls roll back domain updates and are not included in saved usage totals.

## Start with Docker (Windows PowerShell)

Install Docker Desktop with the Linux container engine and Docker Compose, then:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose --env-file .env up --build -d
docker compose logs backend
```

Open http://localhost:5173. API docs: http://localhost:8000/docs.
The dashboard also supports http://127.0.0.1:5173. Both origins are explicitly
allowed by CORS. If the browser reports a connection error, check `docker compose ps`
and start the stack with `docker compose up -d`; static browser content may remain
visible after the backend has stopped.
The backend runs `alembic upgrade head` before starting; migration failure prevents
startup. PostgreSQL data persists in the `postgres_data` volume.
PostgreSQL runs only inside Docker and is not published to a Windows host port;
the backend connects to `db:5432` over the Compose network. No local PostgreSQL
installation is needed. Ollama stays on the configured remote server.

```powershell
docker compose down
```

Example credentials are local development defaults. Change them before sharing an
environment. URL-encode special characters in credentials used in database URLs.
Do not commit `.env`. Compose services bind to localhost.

## Optional local backend development (Windows PowerShell)

Requires Python 3.11+ and Node.js 22+. From the repository root:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose --env-file .env -f docker-compose.yml -f docker-compose.dev.yml up -d db
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -e ./backend pytest httpx ruff
Copy-Item .env backend/.env
# In backend/.env, use localhost:15432 for DATABASE_URL (or your POSTGRES_PORT).
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In a second PowerShell terminal, from the repository root:

```powershell
Set-Content frontend/.env 'VITE_API_BASE_URL=http://localhost:8000'
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

The frontend's `VITE_API_BASE_URL` is public and embedded at build time. Never put
secrets in `VITE_*` variables. Backend configuration uses Pydantic Settings;
`DATABASE_URL` is a secret value and CORS origins are an explicit JSON array.
Local backend commands read `backend/.env`; Compose uses the root `.env`.
The optional development override publishes PostgreSQL on localhost:15432 by
default, avoiding Windows reservations on port 5432. The normal Docker-only run
does not need this override or any database host port.

## Verify

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic check
```

For the Docker-only application, verify migrations and the remote model inside
the backend container (no host PostgreSQL installation or Python environment needed):

```powershell
docker compose ps
docker compose exec backend alembic current
docker compose exec backend alembic check
docker compose exec backend python -m app.check_ollama
docker compose exec backend python -m app.check_ollama --no-probe --update-probe --attempts 1
docker compose logs --tail 50 backend
```

To stop the app: `docker compose down`. This preserves the PostgreSQL volume.

From `frontend`: `npm.cmd run build` runs TypeScript checks and Vite compilation.
From the root: `docker compose --env-file .env build`.
Tests use isolated SQLite databases, exercising API behavior, stale updates,
immutable history, checkpoint persistence, all defined transitions, approval
gates, and Alembic upgrade/check/downgrade. PostgreSQL integration must also be
verified against a running PostgreSQL instance; SQLite is not a substitute for
PostgreSQL concurrency verification.

## Architecture and data flow

`frontend/src` renders the dashboard and sends JSON to FastAPI. `app/api` owns
HTTP operations, `schemas.py` validates request/response boundaries, `models.py`
defines persistence, and `workflows/state.py` defines the state machine.
`services/llm.py` is a provider-independent structured model contract implemented
by the reusable remote Ollama adapter. `services/architecture_gateway.py` remains
an interface only. `analysis_schemas.py` and `services/validation.py` separate
model output from deterministic provenance, ID and answer validation.

Project creation atomically inserts a project and its first checkpoint. A text
submission atomically compares the expected project version, increments it,
inserts an immutable requirement version and writes a JSON checkpoint. Concurrent
stale updates return HTTP 409. Retrying requires fetching the current project.
Submissions are full replacements of the intake document, not separate extracted
requirements. The stable ID `REQ-{project UUID}` identifies that intake document;
extraction assigns project-scoped R001... IDs and Q001... question IDs. Text is
normalized without removing source references. Stated requirements, inferred
assumptions and customer-confirmed updates are labelled separately.

Tables created by revision `0001`:

- `projects`: UUID, name, description, workflow state, concurrency version, timestamps.
- `requirement_versions`: UUID, project FK, stable requirement ID, version, text,
  timestamp; unique project/version.
- `workflow_checkpoints`: UUID, project FK, project version, state, JSON snapshot,
  timestamp; unique project/project-version.
- `alembic_version`: migration revision tracking.

Revision `0002` preserves the initial tables, adds source metadata to intake
versions, and creates `analysis_versions`, `clarification_answers`, and
`graph_runtime`. Analysis versions include effective answers, source evidence,
validated requirements, draft summary and cumulative usage. Answer edits append
revisions; old analysis snapshots preserve the answers effective at that time.

`ba_graph.py` executes extraction/source review, clarification interrupt, deterministic update and
deterministic summary nodes. A SQL-backed transactional saver buffers LangGraph
checkpoints and pending writes without sharing database sessions across worker
threads. Graph runtime, analysis, answer revisions, project state and domain
checkpoints commit together. A fresh backend instance restores and resumes the
saved interrupt with LangGraph `Command(resume=...)`.

Workflow: INTAKE → ANALYZING → AWAITING_CLARIFICATION → ANALYZING →
REQUIREMENTS_REVIEW. With no blockers, analysis goes directly to review. Editing
an answer in review returns through ANALYZING and may reopen clarification.
State transitions are backend-only. No arbitrary transition or approval API is exposed.
Human approval gates are defined separately from permitted edges; future approval
handlers must obtain approval from authenticated humans, never model output.

Defined states: INTAKE, ANALYZING, AWAITING_CLARIFICATION, REQUIREMENTS_REVIEW,
AWAITING_ARCHITECTURE, ARCHITECTURE_REVIEW, GENERATING_BA_ARTIFACTS, VALIDATING,
FINAL_REVIEW, COMPLETED, FAILED. See `TRANSITIONS` for all permitted edges;
COMPLETED and FAILED are terminal. Repair and rejection loops are defined but
not executed beyond the Phase 2 clarification loop.

## Using Phase 2

1. Create a project. Paste plain text or upload a PDF/DOCX/UTF-8 TXT document.
2. Choose **Analyze latest input**. The model extracts structured requirements
   and gap/conflict analysis. Requirement IDs and source refs are validated.
   **Initial BA understanding** appears before the questions, including the
   objectives, scope, roles and assumptions, instead of being hidden in evidence details.
3. Answer the prioritized clarification batch (at most five) using checklist/radio
   options or free text, then choose **Save answers and continue**. A batch uses
   no additional model inference. Select answers are
   validated against options. Conditional questions appear after their parent
   answer is saved. Unanswered prerequisites of blocking children are also required.
4. Each save creates a new analysis version containing explicit customer decision
   requirements. Original documents are not reprocessed and no model rewrites
   customer facts. Existing statements remain traceable to their original source.
5. Editing a parent invalidates dependent answers. Affected requirements are rebuilt
   from the structured baseline and remaining answers, removing obsolete decisions.
6. Once blockers are resolved, download the DRAFT JSON and Markdown summary.
   **Complete BA project description** also displays readable sections and the
   customer decision log alongside the consolidated requirements.
   Open non-blocking questions remain visible and may be answered from review.
   The version selector shows prior immutable analysis snapshots.

For a project created before the business-content fix, choose **Rebuild description
from saved answers** after deploying the updated images. This runs source-support
review once and appends a new analysis version using the answers already saved.
It does not replace intake text, delete old versions, or select unanswered options.
The shopping-platform example still requires Q006 and Q007; the progress panel
shows their question text as blockers rather than silently hiding the final draft.
The working description remains available during clarification.

The summary includes overview, business objectives, scope, roles, functional and
non-functional requirements, rules, constraints, dependencies, assumptions and
open non-blocking questions. It remains DRAFT; the model cannot approve it.

Requests are synchronous. The backend holds a per-project CAS row lock while
processing, preventing concurrent graph writes. It records ANALYZING and the final
state in one transaction; other clients see the previous committed state while
processing. Failures roll back to that checkpoint. Retry the same action after
fixing connectivity/model issues. If the browser lost the successful response,
refresh before retrying to obtain the new project version.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Process liveness; does not claim database readiness |
| POST | `/api/projects` | Create project and initial checkpoint |
| GET | `/api/projects?offset=0&limit=50` | List projects; maximum limit 100 |
| GET | `/api/projects/{id}` | Fetch current state and concurrency version |
| POST | `/api/projects/{id}/requirements` | Save text with `expected_version` |
| GET | `/api/projects/{id}/requirements?offset=0&limit=50` | Read version history |
| POST | `/api/projects/{id}/uploads` | Multipart `file` and `expected_version` |
| GET | `/api/llm/health?probe=true` | Model availability and structured JSON probe |
| POST | `/api/projects/{id}/analyze` | Analyze latest intake with `expected_version` |
| GET | `/api/projects/{id}/analysis?version=1` | Current or historical analysis JSON |
| GET | `/api/projects/{id}/analysis/versions` | Paginated analysis version index |
| POST | `/api/projects/{id}/answers` | Submit/edit up to five answers with `expected_version` |
| POST | `/api/projects/{id}/reconcile` | Recheck source support and rebuild from saved answers; creates a new version |
| GET | `/api/projects/{id}/answers/history` | Paginated immutable answer revisions |
| GET | `/api/projects/{id}/summary.md?version=1` | Current or historical draft Markdown |

```powershell
$project = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/projects -ContentType application/json -Body (@{name="Customer portal"} | ConvertTo-Json)
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/projects/$($project.id)/requirements" -ContentType application/json -Body (@{text="Customers can track orders."; expected_version=$project.version} | ConvertTo-Json)
$current = Invoke-RestMethod "http://localhost:8000/api/projects/$($project.id)"
$analysis = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/projects/$($project.id)/analyze" -ContentType application/json -Body (@{expected_version=$current.version} | ConvertTo-Json) -TimeoutSec 600
# Use actual question IDs and options from $analysis.questions, for example:
# @{expected_version=$analysis.project_version; answers=@(@{question_id="Q001"; value="yes"})} | ConvertTo-Json -Depth 5
```

Names are limited to 200 characters, descriptions to 10,000 and requirement text
to 100,000. Unknown fields and whitespace-only inputs are rejected. Validation
errors do not echo submitted text; database exceptions return a generic response.
SQL query logging is disabled. React renders submitted text as escaped text.

## Document limits and known limitations

This is a local foundation, not a publicly deployable authenticated service.
Authentication, tenancy, rate limits, audit identity, asynchronous job workers and
parser process isolation are future work. Uploads are capped at 5 MiB; all request
bodies at 6 MiB; extracted text at 100,000 characters; PDF pages at 200; expanded
DOCX content at 20 MiB. Extension/MIME/signature checks, encrypted-PDF rejection,
macro rejection, DOCX archive limits and control-character validation apply.
DOCX tables and paragraphs and PDF page/line references are retained. No OCR:
scanned/image-only PDFs are rejected when no text is extracted. No raw upload is
written to application storage. Documents and model output are untrusted data.

Analysis uses an extraction call and a source-support review per document. The remote model must
have enough context/output capacity; large documents may fail or exceed its
capacity. Chunked extraction and cross-chunk reconciliation are not implemented.
Semantic correctness still requires customer review: schema/provenance checks
cannot prove that a model understood every business statement. Invalid model output
is rejected instead of silently inventing or accepting a repair. The checkpoint
buffer retains runtime history and may need pruning for long editing histories.

Later phases may add authenticated approval records, architecture integration,
epics/stories/tasks and artifact quality repairs. None is implemented in Phase 2.

## Phase 1 verification record

Executed during implementation: Ruff check passed; pytest passed all 5 tests;
TypeScript/Vite production build passed; Docker Compose configuration validation
passed. Migration upgrade, schema comparison and downgrade ran on SQLite in tests.

Docker image builds were attempted and failed because Docker Desktop's Linux
engine was unavailable: `open //./pipe/dockerDesktopLinuxEngine: The system cannot
find the file specified.` PostgreSQL migrations and runtime behavior have not
been verified against a live server. Start Docker Desktop and rerun the Docker
commands above to complete that verification.

The installed `uv.exe` launcher failed with `No application is associated with
the specified file for this operation`; setup and checks used `python -m venv`
and pip instead. Dependency installation required network access outside the
sandbox after pip reported `WinError 10013` (socket access forbidden).

## Phase 2 verification record

- Ruff passed; all 47 pytest cases passed, with the LLM mocked in automated tests.
- TypeScript checks and the Vite production build passed.
- Alembic upgrade/schema comparison/downgrade passed on SQLite. An additional test
  verified that existing Phase 1 project and intake data survive revision `0002`.
- Both Docker images built successfully. Frontend, backend and PostgreSQL started
  in Docker; backend and database health checks passed.
- Live PostgreSQL inside Docker is at `0002 (head)`; `alembic check` detected no drift.
- The configured remote model was available and a small structured JSON probe
  passed from both the host and the backend container.
- Full analysis against the configured remote model was **not verified successfully**:
  full-schema requests returned HTTP 500 and the compact-schema retry timed out
  at the configured 120 seconds. No models were pulled or installed. The app
  reports these failures and preserves its previous committed workflow checkpoint.

For slow models, increase `OLLAMA_TIMEOUT_SECONDS` in `.env` to an appropriate
value (up to 600), or choose another model already available on the remote server.
Inspect the remote server logs for HTTP 500 errors and capacity issues. Apply
environment changes with `docker compose up -d --force-recreate backend`.
The small health probe verifies basic schema support, not full analysis throughput.

Subsequent latency tuning enabled `OLLAMA_THINK=low` for the configured reasoning
model and capped output at 4096 tokens. A live synthetic full-analysis probe then
succeeded in 54.3 seconds, returning validated requirements and two clarification
questions and pausing at the LangGraph interrupt. This is a sample measurement,
not a response-time guarantee for larger documents. The updated test suite passed
all 51 tests, including generation timeout and reasoning/output controls.

The subsequent clarification fix passed 54 tests, Ruff and the frontend production
build. A live synthetic targeted update against the configured remote model
completed in 5.6 seconds, produced validated requirement updates and a DRAFT
description with a customer decision log. No customer project was modified by
the probe. New descriptions and answer batches require no database migration;
existing persisted clarification checkpoints remain compatible.

Windows initially denied binding host port 5432. The standard Compose stack now
uses only Docker's internal database network and does not publish that port.
The optional development override publishes port 15432 for a host-run backend.

## Latest business-content correction

Implemented explicit, stable decision requirements containing the customer's exact
selected values; unchanged original statements keep their original provenance.
Answer saves no longer invoke Ollama. Deferred/TBD answers remain unresolved.
Initial extraction now includes a separate structured source-support review;
unsupported elaborations are presented as assumptions with review notes.
The dashboard shows one current working description, gap statuses, question progress
and exact completion blockers. Original interpretation and technical evidence are
collapsed reference views. DRAFT exports appear only when required clarifications
and source review are complete.

Latest local verification: Ruff passed, 60 pytest tests passed, and the frontend
TypeScript/Vite build passed. Content tests cover payment and delivery choices,
unchanged provenance, unsupported CRUD, deferred answers, conditional gaps, stable
IDs after edits, and version-preserving reconciliation. The Docker deployment
request for this correction was denied, so these changes have not been applied
to the running containers and the saved customer project has not been reconciled.

To apply the prepared changes:

```powershell
docker compose up --build -d
```

Then reload the dashboard and rebuild the saved description. The source-support
review remains an LLM judgment requiring customer review; it is not a proof of
entailment or authorization to approve requirements.
