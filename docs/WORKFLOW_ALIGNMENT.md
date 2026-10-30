# Workflow diagram alignment

The diagrams describe the whole platform. The current implementation completes the
requirements stage through approval of business understanding and a durable handoff.
This approval does not approve solution design. The diagram's BA Phase 2 (post-architecture
artifacts) is a future stage, distinct from this repository's requirements-analysis Phase 2.

| Diagram step | Current behavior |
| --- | --- |
| BRD or text intake | Versioned text, PDF, DOCX and UTF-8 TXT with upload validation |
| Parse and chunk | 6,000-character chunks; oversized sources split with part references; maximum 32 chunks |
| Extract and normalize | Structured requirements, stable ID remapping and source references; exact duplicate consolidation |
| Analyze gaps and conflicts | Per-chunk analysis plus cross-chunk review for multi-chunk documents; separate grounding review |
| Clarify | Prioritized checklist/free-text questions, conditions, persisted pause/resume, targeted answer assessment |
| Update requirements | Atomic interpreted decisions with answer provenance and historical versions; no full extraction per answer |
| Generate/edit summary | Draft JSON/Markdown; editorial overview/notes revisions; business changes reopen clarification |
| User approves summary | Explicit confirmation of exact analysis/summary revision, optimistic concurrency, immutable snapshot/hash |
| Architecture Agent | Handoff persisted atomically with approval; pending integration; no architecture generated |
| Architecture review/approval | Future work |
| Epics, stories, acceptance criteria, tasks, final BA approval | Future work; UI shows locked/planned stages |

## Review flow

Create a project, save requirements, then analyze. Review the initial understanding and resolve
blocking clarifications. Review the draft under Requirement Summary. Editorial edits adjust
the overview/notes; business changes use Return to clarification. This creates a new blocking
question and persisted analysis version, retaining existing answers. Enter a reviewer name
and explicitly confirm business understanding. Approval freezes the reviewed version and moves
the project to AWAITING_ARCHITECTURE. Approved baselines cannot be reopened in this MVP;
future changes need explicit change control.

The dashboard shows the overall journey and pending integrations. Grounding and semantic
answer reviews remain probabilistic assessments; deterministic validation and human review
remain necessary. Chunking adds model calls and can increase latency. Cross-chunk review and
grounding must still fit the remote model's context window. Reviewer names are self-declared:
authentication, role authorization and verified reviewer identity are not implemented.

## API and persistence

New endpoints under `/api/projects/{project_id}`:

- `GET /summary-review`: current review, revisions and handoff status.
- `POST /summary-revisions`: editorial overview/notes, reviewer, expected project version and analysis version.
- `POST /summary-changes`: feedback, optional affected requirement IDs, expected project version and analysis version.
- `POST /summary-approval`: expected project version, analysis version, exact summary revision, reviewer and `confirm_business_understanding: true`.

Migration 0004 adds `summary_revisions`, `requirements_approvals`, `architecture_handoffs`.
Approval snapshots contain structured requirements, answers, summary and SHA-256 content hash.
Handoffs remain PENDING_INTEGRATION. No external architecture service is contacted.

## Windows PowerShell

From the repository root, preserve the existing `.env` and remote Ollama settings.
PostgreSQL runs in Docker; no local PostgreSQL installation is needed.

```powershell
docker compose up --build -d
docker compose logs --tail 100 backend
# Startup runs Alembic upgrade head, including migration 0004.
# UI: http://localhost:5173 ; API docs: http://localhost:8000/docs

Push-Location backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
Pop-Location
Push-Location frontend
npm.cmd test -- --run
npm.cmd run build
Pop-Location
```

These are run instructions, not a claim that the running Docker deployment was updated.
No Docker deployment or live remote-model test was performed for this change. Automated tests
use mocked model responses and SQLite; PostgreSQL/model integration requires a Docker run.

Executed verification: Ruff passed; 87 backend pytest tests passed (including Alembic
upgrade/downgrade, schema drift and existing-data preservation); 10 frontend tests passed;
TypeScript/Vite production build passed. Docker image builds were not run for this update.
