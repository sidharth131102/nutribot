# NutriBot v2 Roadmap

> **Purpose of this document**: a self-contained phase plan for anyone (human or AI agent) picking up this project cold. It answers "what is this project trying to become, in what order, and how far along is it?" For a detailed, chronological build log of *how* each phase was implemented (files touched, design decisions, live-verification notes), see `docs/CURRENT_STATE.md`. For a catalog of every significant bug hit and how it was fixed, see `docs/ISSUES_AND_FIXES.md`.

## What this project is

NutriBot is an AI nutrition assistant: a FastAPI + LangGraph backend (multi-node agent pipeline) with a Next.js frontend, MongoDB Atlas for storage, Pinecone for RAG, and Azure OpenAI for generation. The v2 rebuild (this roadmap) originated from a user-provided planning document, `NutriBot_v2_Roadmap.md`, which was never itself committed to this repo — this file (`docs/ROADMAP.md`) is the in-repo record of that plan, kept current as phases complete.

## Six non-negotiable invariants

These apply to **every** phase. If a task seems to require weakening one of them, stop and flag it rather than proceeding.

1. **The LLM never does deterministic math.** `backend/tools/calorie_tool.py` owns all BMR/TDEE/macro arithmetic (Mifflin-St Jeor formula). The LLM only consumes the computed numbers, never invents or recalculates them.
2. **`data/food_db.json` is the sole macro source of truth.** Any food's calorie/protein/carb/fat values come from this file, never from the LLM.
3. **Safety constraints (allergen/diet/medical) are enforced via a pre-generation allow-list**, not prompt instruction alone. `backend/utils/food_filter.py::get_filtered_foods()` is the enforcement point; `backend/agents/meal_plan_agent.py::_sanitize_plan()` is the post-generation backstop.
4. **User isolation is enforced at the data-access layer**, never by prompt instruction or convention. `backend/db/mongo.py::UserScopedRepo` makes this structural — every method is constructed with a `user_id` and scopes every query by it.
5. **The system extracts/reports medical facts, it never diagnoses.** Applies to memory extraction (`backend/memory/extraction.py`), medical document processing (`backend/documents/extraction.py`), and the output guardrail (`backend/guardrails/output_check.py`).
6. **Generation is swappable behind one provider interface** — no agent or module calls a vendor SDK directly except the one file designated to own that vendor. See `backend/llm/base.py::LLMProvider` and the "one file owns one external service" pattern used throughout (`azure_openai_provider.py`, `blob_storage.py`, `doc_intelligence.py`, `bm25_index.py`, `deepeval_provider.py`, etc.).

## Infrastructure: Vercel is interim, Azure is the target

**Decision (confirmed with the user, 2026-08-02): this roadmap is authoritative on infrastructure, not whatever is deployed today.** The app currently runs on Vercel (two projects: backend + frontend serverless). That is explicitly an **interim state**, not a redirection of the plan. Phase 9 means migrating off Vercel to Azure Container Apps (backend) + Azure Static Web Apps (frontend) + Azure Key Vault (secrets) — Azure Blob Storage and Document Intelligence (Phase 4) are already live on Azure today, ahead of that full migration.

**Practical implication for future phases**: don't substitute a Vercel-native service (e.g. Vercel Blob) for what the roadmap specifies as an Azure service — Phases 4, 7, 8, 9 are meant to be built against real Azure services even while the rest of the app still runs on Vercel.

## Phase status

| Phase | Name | Status | Shipped |
|---|---|---|---|
| 0 | Repo recon | ✅ Done | 2026-08-02 |
| 1a | Provider abstraction | ✅ Done | 2026-08-02 |
| 1b | Evaluation harness | ✅ Done | 2026-09-03 |
| 1c | Hardening (secrets/logging/CI/tests) | ✅ Done (scoped subset) | 2026-09-03 |
| 2 | Compliance & data isolation | ✅ Done (backend-only) | 2026-09-03 |
| 3 | 4-layer memory system | ✅ Done | 2026-09-03 |
| — | LLM provider: Groq → Azure OpenAI | ✅ Done | 2026-09-07 |
| 4 | Medical document pipeline | ✅ Done | 2026-09-08 |
| 5 | RAG 2.0: hybrid search + reranking | ✅ Done | 2026-09-08 |
| 6 | Guardrails + rate limiting + observability | ✅ Done | 2026-09-11 |
| 7 | Azure AI Foundry challenger model (eval-gated) | ⬜ Not started | — |
| 8 | Fine-tuning (optional, only if Phase 7 shows stock models fall short) | ⬜ Not started | — |
| 9 | Azure production hardening (full Vercel→Azure migration) | ⬜ Not started | — |
| — | Frontend UI for Phase 2/4 features (consent/export/delete/documents) | ⬜ Not started | — |

## Phase-by-phase detail

### Phase 0 — Repo recon (done)
Ground-truthed the existing codebase against the roadmap's assumptions before building anything. Found: vector store was ChromaDB (migrated to Pinecone same session, for Vercel-serverless compatibility — local disk doesn't survive serverless cold starts); calorie math was already cleanly deterministic (invariant 1 held); no provider abstraction existed (both `meal_plan_agent.py` and `intent_agent.py` imported `langchain_groq.ChatGroq` directly); the food allow-list existed but had no post-generation enforcement (the exact gap Phase 6 later closed); `tests/` was empty; a `NUTRIBOT_MAX_GENERATION_RETRIES` setting was documented in the README but never implemented anywhere — dead documentation.

### Phase 1a — Provider abstraction (done)
Built `backend/llm/` (`base.py`'s `LLMProvider` ABC + `Message`/`GenerationConfig`/`GenerationResult`, `groq_provider.py`, `factory.py`'s `get_provider()`). Every agent now calls `get_provider().generate(...)` instead of a vendor SDK directly — this is what let the later Groq→Azure migration happen as a provider-registry addition instead of an agent-by-agent rewrite.

### Phase 1b — Evaluation harness (done)
`backend/eval/`: a 16-case golden set (2 cases × 8 categories: general_qa, meal_plan_request, plan_modification, allergy_diet_edge_case, medical_context, ambiguous_unsafe, rag_dependent, structured_output), a pipeline runner that exercises real agent node functions without touching MongoDB, a deterministic scorer, and (originally) an LLM-judge stub — replaced by real DeepEval metrics in Phase 6. Run manually via `python -m backend.eval.runner`; deliberately excluded from CI (real API cost + rate-limit risk on every commit is the wrong tradeoff for an auto-triggered gate).

### Phase 1c — Hardening (done, scoped subset)
Secrets boot-guard (refuses to start in `ENVIRONMENT=production` with insecure defaults), structured JSON logging with a per-request `trace_id` (contextvar-based, zero changes needed at existing log call sites), Dockerfile + docker-compose, GitHub Actions CI. Rate limiting and login brute-force protection were **explicitly deferred** here, bundled with the Groq migration — later delivered in Phase 6.

### Phase 2 — Compliance & data isolation (done, backend-only)
`UserScopedRepo` makes user-id scoping structural across all authenticated data access (invariant 4). Consent model (append-only event log, gates writes of `medical_conditions`), `GET /api/user/export`, `DELETE /api/user/account`, 90-day-TTL access audit log. No frontend UI built for any of this — a backend-only scoping decision that has persisted through every later phase that added more personal-data endpoints (documents in Phase 4).

### Phase 3 — 4-layer memory system (done)
Profile (MongoDB `users` — always-current fields) + short-term (rolling chat window) + long-term semantic (`memories` collection, extracted via a gated LLM call — not every turn, to control cost — with category-based supersession) + episodic (`episodic_events` — goal changes, accepted plans). A `Context Builder` (`backend/context/builder.py`) assembles all of this into one typed object per generation call, replacing ad hoc prompt string-building.

### LLM provider migration: Groq → Azure OpenAI (done, 2026-09-07)
Not a roadmap-numbered phase, but the single most consequential infra change of the whole project: Groq's free tier's 8000 TPM shared rate limit was truncating ~50% of plan-generating requests even after aggressive mitigation. Migrated to Azure OpenAI (`gpt-5-mini-1`, ~100K+ TPM headroom) via the Phase 1a provider abstraction — a registry addition, not an agent rewrite. Groq stays registered as a fallback option, not deleted. See `docs/ISSUES_AND_FIXES.md` for the six distinct bugs hit during this migration.

### Phase 4 — Medical document pipeline (done)
Users upload a medical report (PDF/JPG/PNG); Azure Document Intelligence OCRs it; an LLM extracts factual statements (invariant 5: never diagnoses) into the *existing* `memories` collection (`category: "medical_history"`) — because the Context Builder renders memories regardless of source, this needed zero LangGraph changes. New `backend/documents/` module. Three deletion modes (single/batch/clear-all), all of which remove the file but deliberately keep extracted memory facts.

### Phase 5 — RAG 2.0: hybrid search + reranking (done)
Retrieval was pure Pinecone semantic search with no keyword component and no reranking. Now: Pinecone dense search + in-process BM25 keyword search (`rank-bm25`, no new infra — the knowledge base tops out around ~50 documents, comfortably within the range an in-memory index handles), fused via Reciprocal Rank Fusion, reranked by the existing LLM provider down to the final top-k. New local corpus file `data/rag_corpus.json` (committed to git, written alongside every Pinecone upsert).

### Phase 6 — Guardrails, rate limiting, LangSmith, DeepEval (done)
The user explicitly wanted production-grade behavior, not just eval-time quality checks. Runtime input guardrail (blocks medical emergencies/medication misuse/self-harm with a fixed vetted response, never LLM-authored safety text) and output guardrail (allergen-in-prose scan + diagnosis-language/fabricated-claims check, one automatic regeneration attempt, safe fallback if still unsafe) — both live on every real chat message, not eval-only. Mongo-backed rate limiting (no Redis exists in this codebase). Opt-in LangSmith tracing. The eval harness's judge is now real DeepEval metrics (replacing a hand-rolled stub), gating the harness's exit code for safety-relevant categories. See `docs/ISSUES_AND_FIXES.md` for 6 bugs found during a deliberate full-code-review pass before the final live verification.

### Phase 7 — Azure AI Foundry challenger model (not started)
Per the original roadmap: introduce a second, Azure-AI-Foundry-hosted model as a "challenger" to the current primary model, evaluated via the Phase 1b/6 eval harness before being promoted. Open decisions not yet made (flagged since Phase 0): Foundry serverless vs. dedicated hosting, and how a challenger model plugs into the existing provider-registry pattern (`backend/llm/factory.py`) — likely a third registry entry, consistent with how Azure OpenAI was added alongside Groq.

### Phase 8 — Fine-tuning (not started, conditional)
Explicitly optional per the original roadmap — only pursue if Phase 7's evaluation shows stock/off-the-shelf models underperforming on this domain in a way fine-tuning would plausibly fix. Not a default next step.

### Phase 9 — Azure production hardening (not started)
The full Vercel → Azure migration: Azure Container Apps (backend), Azure Static Web Apps (frontend), Azure Key Vault (secrets, replacing plain env vars). Blob Storage and Document Intelligence (Phase 4) are already live on Azure, ahead of this — Pinecone (a hosted, non-Azure vector store) is expected to remain as-is unless a specific reason to migrate it emerges.

## What's next

Two reasonable next steps, not yet decided between:
1. **Phase 7** (Azure AI Foundry challenger model) — continuing the roadmap's numbered sequence.
2. **A frontend UI** for the several backend-only features that have accumulated across Phases 2, 4, 5, and 6 (consent management, data export/delete, medical document upload/list/delete) — none of these have any UI yet, by deliberate scoping decision at the time, but the gap is now fairly large.

Check with the user rather than assuming which one they want.

## Open items carried from the original roadmap, not yet resolved

- Judge coverage thresholds — **resolved in Phase 6** (DeepEval gates on safety-relevant categories).
- Reranker model/placement — **resolved in Phase 5** (LLM-based via the existing provider, in-process BM25 fusion).
- Foundry serverless-vs-dedicated hosting — still open, Phase 7's job.
- Data retention windows — partially resolved (90-day TTL on `access_audit`, per-user hard delete via `DELETE /api/user/account`); no broader retention policy beyond that has been decided.
- RAG-mode disclosure (telling the user when a response is/isn't grounded in retrieved clinical content) — not yet addressed by any phase.
