# BA workspace review and correction

## Root causes

- Resolution previously depended on nonempty text and a short undecided-word list.
  Random free text could therefore resolve a gap without answering its question.
- Answer generation rendered a Q&A template rather than interpreting atomic requirements.
- Original, inferred and customer-confirmed statements were not clearly separated in the UI.
- The page combined intake, evidence, all answer editors, summaries and history.
- Failed validations had no durable review/confirmation audit, and response latency was
  difficult to distinguish from repeated model calls.

## Current flow and confirmation policy

FastAPI remains the workflow authority. Deterministic validation checks question/version
membership, types, required values, option membership, exclusive/conflicting choices,
duplicate submissions and active conditional dependencies. Existing request bodies remain
supported; the new UI also sends the analysis version as `question_version`.

A targeted Ollama request assesses submitted answers and produces `VALID`, `INCOMPLETE`,
`UNCLEAR`, `CONTRADICTORY` or `NEEDS_REVIEW`, a reason, suggested clarification and atomic
interpretations. It receives questions/answers and existing question/key metadata, not the
entire original document. Each interpreted requirement must cite an exact answer excerpt.
Model-created Q&A-template requirements are rejected. New provider names, quantitative targets
or business decisions must not be invented. Relevant missing details become deduplicated,
conditional, non-blocking follow-up questions.

Only VALID decisions, or explicitly confirmed INCOMPLETE/NEEDS_REVIEW interpretations,
can resolve gaps. Confirmation needs a rationale and a grounded interpretation. The original
uncertain status, rationale and confirmation request are retained. UNCLEAR/CONTRADICTORY
answers cannot bypass validation; undecided answers stay unresolved. Unusual but clear
decisions are not rejected by a vendor or technology allowlist.

Save draft stores the input without model inference and without resolving the question.
Invalid semantic answers are persisted as unresolved revisions, so entered text and audit
history survive reloads. Network/model failure rolls back the attempted transaction and the
browser retains its draft. Edits re-evaluate affected decisions, invalidate conditional child
answers and remove obsolete interpreted requirements. Unchanged decisions are reused.

Atomic clauses use persistent question/semantic-key ID mappings, trace to an answer revision,
and appear as CUSTOMER_CONFIRMED. Existing source facts remain STATED, unsupported elaborations
INFERRED, and unresolved decisions stay in clarification rather than becoming business rules.
Gap states are OPEN, AWAITING_ANSWER, ANSWER_NEEDS_CLARIFICATION, RESOLVED and DEFERRED.
No Architecture Agent, final approval or cloud deployment was added.

## Workspace

- Sidebar: Dashboard, Requirements, Clarifications, Requirement Summary, Version History.
- Dashboard: counts, workflow status, intake, upload and recent activity.
- Requirements: search/type/classification filters, stable IDs, titles and expandable traceability.
- Clarifications: one active question, manageable queue, inline feedback, save draft,
  explicit confirmation, previous-answer selector, progress and version-aware submission.
- Summary: safe rendering of the application's generated Markdown subset; raw HTML stays inert;
  DRAFT badge and disabled exports while blocking decisions remain unresolved.
- History: friendly version/revision labels, timestamps and workflow events.
- Diagnostics: collapsed token/latency/attempt metrics, validation audit and technical IDs.

The interface uses responsive local CSS, native accessible controls and reduced-motion
support. No additional production UI library or external font service is required.

## Files

Backend: `analysis_schemas.py`, `models.py`, `services/validation.py`, `services/answer_review.py`,
`services/business_quality.py`, `services/analysis.py`, `workflows/ba_graph.py`, `api/analysis.py`
and `check_ollama.py`. Existing project/intake endpoints and workflow definitions are preserved.

Frontend: `Workspace.tsx`, `ClarificationEditor.tsx`, `RequirementsView.tsx`,
`MarkdownDocument.tsx`, `workspaceTypes.ts`, `workspace.css`, and `main.tsx`.
Test tooling is in package.json/package-lock.json and vitest.config.ts.

Migration `0003_answer_validation` creates `answer_validation_events`; it does not delete
or rewrite existing project, requirement, answer or checkpoint records. Older analyses can be
revalidated from the dashboard, creating another analysis version. Saved uncertain confirmations
are retained when their unchanged answers are reused.

## Run on Windows PowerShell

Keep your existing `.env`, remote Ollama URL and model. No Ollama installation or model pull
is needed. PostgreSQL stays inside Docker.

```powershell
docker compose up --build -d
docker compose exec backend alembic current
docker compose exec backend alembic check
```

Open http://localhost:5173 or http://127.0.0.1:5173. If prompted, use **Revalidate saved
analysis** before continuing an older project. Migration 0003 must run before the new APIs.

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
Pop-Location
Push-Location frontend
npm.cmd ci
npm.cmd test
npm.cmd run build
Pop-Location
```

Final executed results: **79 pytest tests passed**, **8 frontend tests passed**, Ruff passed,
and TypeScript/Vite production build passed. The frontend dependency install reported zero
known vulnerabilities after updating the test runner. Tests cover the existing APIs alongside
the new semantic, draft, confirmation, stale-version, conditional and atomic-requirement paths.

The tests mock Ollama for deterministic results. Alembic upgrade/check/downgrade and preservation
of Phase 1 data are tested on isolated SQLite databases. Live PostgreSQL migration and remote
Ollama end-to-end checks are separate from these automated checks; they are not implied by a
successful frontend build. Docker deployment was not repeated after the earlier denied deployment.

## Remaining limits

Semantic interpretation is model-assisted, not proof of business correctness; customer review
is still required. Provider latency is measured per successful call rather than attributed to
hardware or network without evidence. Work remains synchronous per project with bounded retries
and timeouts. Authentication/tenant isolation and full browser end-to-end tests are outside
this correction. The test suite verifies UI behavior in jsdom, not a live browser/device matrix.
