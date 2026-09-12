# NutriBot — Project Context

> **Read this first, before changing anything.** This is the orientation document: how the system currently fits together, what you must not break, and where to look for more detail. It is not a build log (`CURRENT_STATE.md`), not a phase plan (`ROADMAP.md`), not a bug catalog (`ISSUES_AND_FIXES.md`) — it's the map that tells you which of those to open for what, plus the constraints that don't show up clearly in any single file's diff.

## Doc map — which file answers which question

| Question | File |
|---|---|
| "How do I set this up and run it?" | `README.md` |
| "What's the plan, and what phase are we on?" | `docs/ROADMAP.md` |
| "How did we get here — what shipped in each phase, file by file?" | `docs/CURRENT_STATE.md` |
| "What bugs have we already hit, and how were they fixed?" | `docs/ISSUES_AND_FIXES.md` |
| "How does the system actually work right now, and what must I not break?" | **this file** |

Read `ISSUES_AND_FIXES.md`'s "cross-cutting patterns" section too — three bug classes (reasoning-model empty output, missing LLM-call timeouts, substring matching on safety text) have each recurred multiple times across different phases. Don't reintroduce them.

## What this project is, in one paragraph

NutriBot is an AI nutrition assistant: a FastAPI backend running a 10-node LangGraph agent pipeline (input safety check → profile → memory retrieval → intent classification → calorie math → RAG retrieval → food filtering → meal plan generation → output safety check → memory extraction), backed by MongoDB Atlas (user data), Pinecone (hybrid-search RAG over clinical guideline PDFs), and Azure OpenAI (generation). A Next.js frontend exists but has not been updated for anything built since Phase 1 — every feature from Phase 2 onward (consent, document upload, export/delete) is backend/API-only. Phases 0-6 of a 10-phase roadmap are done (see `docs/ROADMAP.md` for what that means).

## System architecture

### The agent pipeline (`backend/agents/graph.py`)

```
input_guardrail → [blocked? → END]
      ↓ continue
   profile → memory_retrieval → intent → [route by intent]
      ↓
   calorie? → rag? → food? → meal_plan
      ↓
   output_guardrail → [regenerate? → back to meal_plan, once] → [extract? → memory_extraction] → END
```

This is a **LangGraph `StateGraph`**, compiled once (`get_compiled_graph()`, module-level singleton) and invoked per-request via `run_chat_pipeline(user_id, session_id, user_message)`. State is one `TypedDict` (`backend/agents/state.py::NutriBotState`, `total=False`) threaded through every node — any node can read any prior node's output by key, there's no per-node schema validation. **When you add a new field to state, add it to `NutriBotState` too**, even though `TypedDict` won't enforce it at runtime — it's the only documentation of what's in the state bag.

**Routing is intent-keyed**, not free-form: `_route_after_intent`/`_route_after_calorie`/`_route_after_rag`/`_route_after_meal_plan`/`_route_after_input_guardrail`/`_route_after_output_guardrail` in `graph.py` are pure functions, each returning a string key that maps to a `graph.add_conditional_edges(...)` destination dict. If you add a new intent or a new routing condition, it has to be threaded through the relevant `_route_after_*` function AND the corresponding `add_conditional_edges` mapping, or LangGraph will raise at graph-build time (a destination key must exist in the mapping for every value the routing function can return).

**The output-guardrail cycle is bounded, verify this stays true if you touch it**: `meal_plan → output_guardrail` can route back to `meal_plan` at most `MAX_OUTPUT_REGENERATIONS` times (currently 1, `backend/guardrails/nodes.py`) before it's forced to a fixed fallback response and `guardrail_blocked=True`. The count lives in state (`guardrail_regeneration_count`) and strictly increases — there is no path that resets it mid-turn. Don't remove the cap or make it settings-configurable without also re-verifying by hand that it still terminates (see `ISSUES_AND_FIXES.md` — this was explicitly hand-traced during Phase 6 review).

**Two agents run outside the graph entirely**: `backend/agents/memory_agent.py::save_accepted_plan` and `backend/agents/email_agent.py::deliver_plan_email`, both called directly from `backend/main.py`'s `/api/plans/accept` endpoint, not as pipeline nodes.

### Directory map (`backend/`)

| Directory | Owns |
|---|---|
| `agents/` | The 10 LangGraph nodes + `state.py` (shared state shape) + `graph.py` (topology/routing) |
| `guardrails/` | Runtime input/output safety checks (Phase 6) — `input_check.py`, `output_check.py`, `nodes.py` (LangGraph adapters), `models.py` |
| `llm/` | The `LLMProvider` abstraction (`base.py`), `factory.py` (`get_provider()` registry), one file per vendor (`azure_openai_provider.py`, `groq_provider.py`) |
| `rag/` | Retrieval: `retriever.py` (the hybrid pipeline), `bm25_index.py`, `fusion.py`, `reranker.py`, `ingest.py` (PDF → Pinecone + local corpus) |
| `documents/` | Medical document upload pipeline (Phase 4) — `blob_storage.py`, `doc_intelligence.py`, `extraction.py`, `validation.py` |
| `memory/` | Long-term semantic memory extraction (Phase 3, chat-turn-based; distinct from `documents/extraction.py`, which extracts from uploaded files) |
| `context/` | `builder.py::build_context()` — assembles a `GenerationContext` from state for prompt-building, the single place that replaced ad hoc `state.get(...)` scattered through prompt code |
| `db/` | `mongo.py` (`UserScopedRepo`, the user-isolation layer, + `ensure_indexes()`), `vector_store.py` (Pinecone client) |
| `security/` | `rate_limit.py` — Mongo-backed rate limiting (Phase 6) |
| `eval/` | The offline evaluation harness — golden set, pipeline runner (real node functions, no MongoDB), deterministic + DeepEval scorers |
| `tools/` | `calorie_tool.py` (the ONLY place BMR/TDEE/macro math happens — invariant 1), `email_tool.py` |
| `utils/` | `food_filter.py` (the pre-generation allow-list — invariant 3) |
| `models/` | Pydantic request/response/DB schemas, one file per domain |
| `auth/` | JWT + Google OAuth |
| `observability.py`, `config.py`, `main.py` | Cross-cutting: logging/tracing, settings, the FastAPI app itself |

### "One file owns one external service" — the current full list

This pattern (invariant 6) means: if you need to call a vendor SDK, find the file that already owns it, or create a new dedicated one — never call a vendor SDK inline from an agent, guardrail, or anywhere else.

| Vendor / concern | Owning file |
|---|---|
| Azure OpenAI generation | `backend/llm/azure_openai_provider.py` |
| Groq generation (fallback provider, not currently active) | `backend/llm/groq_provider.py` |
| Azure Blob Storage | `backend/documents/blob_storage.py` |
| Azure Document Intelligence | `backend/documents/doc_intelligence.py` |
| Pinecone | `backend/db/vector_store.py` (client), `backend/rag/retriever.py` (queries) |
| In-process BM25 | `backend/rag/bm25_index.py` |
| DeepEval's judge LLM | `backend/eval/deepeval_provider.py` (routes back through `get_provider()` — DeepEval itself never gets its own vendor credentials) |
| MongoDB | `backend/db/mongo.py` |
| SendGrid | `backend/tools/email_tool.py` |
| Google OAuth | `backend/auth/google_oauth.py` |

**Any brand-new external dependency gets its own file, following this same shape**: a thin wrapper with no business logic, business logic (auth checks, user scoping, validation) stays in the caller.

### The provider abstraction (why you can swap LLM vendors without touching agents)

`backend/llm/base.py` defines `Message`, `GenerationConfig` (`profile: "fast"|"full"`, `temperature`, `max_tokens`), `GenerationResult`, and the `LLMProvider` ABC (`async generate(messages, config) -> GenerationResult`). Every agent, guardrail, and eval scorer calls `get_provider().generate(...)` — never a vendor SDK directly. `backend/llm/factory.py::get_provider()` is `@lru_cache`d and picks a provider class from a registry keyed on `settings.llm_provider`. **This is exactly how the Groq → Azure OpenAI migration happened as a registry addition instead of an agent-by-agent rewrite** — if Phase 7 adds an Azure AI Foundry challenger model, it's a third registry entry, not a new code path through every agent.

**Currently active**: `LLM_PROVIDER=azure_openai` (`.env`), deployment `gpt-5-mini-1` for both `fast` and `full` profiles. Groq stays registered as a fallback option, not deleted — if you ever flip `LLM_PROVIDER=groq` back on, **the token budgets need lowering again** (see the "if Groq is reactivated" notes throughout `CURRENT_STATE.md` — `max_tokens`, food list size, RAG context cap, and chat history window were all raised for Azure's much higher quota and will cause truncation again under Groq's 8000 TPM ceiling).

**GPT-5-family models are reasoning models with quirks** (see `ISSUES_AND_FIXES.md` #8/#20/#31 for the full incident history): they reject a custom `temperature` (Azure's provider file doesn't pass one), they spend hidden tokens on reasoning before the visible answer (`reasoning_effort` is set profile-aware: `"minimal"` for fast, `"low"` for full — DeepEval's wrapper needs `"full"`-tier budget even for what looks like a simple call), and every single `AzureChatOpenAI` construction sets an explicit `timeout=120, max_retries=2` — never omit this for a new LLM call site in this codebase, a request hung for hours once with no timeout set.

### Data layer: `UserScopedRepo` (invariant 4, enforced structurally)

`backend/db/mongo.py::UserScopedRepo` is constructed with an authenticated `user_id` and injects `{"user_id": ...}` into every query by construction — not by convention, not by a parameter callers have to remember to pass. **Every authenticated endpoint in `main.py` constructs `UserScopedRepo(get_db(), user_id)` and calls methods on it; nothing queries MongoDB directly with a bare `user_id` string argument.** If you add a new authenticated data type, add its methods to this class, following the existing pattern (see `get_document`/`delete_document` for the "scope by `_id` AND `user_id` in one query" pattern that makes a leaked/guessed id 404 instead of ever returning another user's data).

**Pre-auth flows** (registration, login, OAuth callback — no `user_id` exists yet) use free functions (`get_user_by_email`, `create_user`, etc.) instead, by necessity — this is the one deliberate exception to "always go through `UserScopedRepo`."

### Current MongoDB collections

| Collection | Purpose | Added |
|---|---|---|
| `users` | Profile, auth | Phase 0 |
| `chat_sessions` | Message history | Phase 0 |
| `accepted_plans` | Last 2 accepted meal plans | Phase 0 |
| `consents` | Append-only consent event log | Phase 2 |
| `access_audit` | Medical-data access log, 90-day TTL | Phase 2 |
| `memories` | Long-term semantic facts (`category`: `preference`/`dislike`/`goal_context`/`lifestyle`/`medical_history`) | Phase 3, extended Phase 4 |
| `episodic_events` | `goal_change`/`plan_accepted` events | Phase 3 |
| `medical_documents` | Uploaded document metadata (bytes live in Blob Storage, not Mongo) | Phase 4 |
| `rate_limit_counters` | Fixed-window rate-limit counters, TTL-cleaned | Phase 6 |

Whenever you add a collection that holds per-user data, it needs entries in **three** places or Phase 2's compliance guarantees silently stop covering it: `ensure_indexes()` (index it by `user_id`), `UserScopedRepo.export_all()`, and `UserScopedRepo.delete_all()`.

## The six invariants — where they're actually enforced in code today

(Full statement of each is in `docs/ROADMAP.md`. This table is "where do I look to confirm it still holds.")

| # | Invariant | Enforcement point |
|---|---|---|
| 1 | LLM never does deterministic math | `backend/tools/calorie_tool.py::compute_calories()` — `calorie_agent.py` calls only this, zero LLM involvement |
| 2 | `food_db.json` is the sole macro source of truth | `backend/utils/food_filter.py` reads it; nothing else defines a food's macros |
| 3 | Safety via pre-generation allow-list | `get_filtered_foods()` (pre-gen filter) + `meal_plan_agent.py::_sanitize_plan()` (post-gen deterministic strip) + `guardrails/output_check.py` (prose-level check, Phase 6) |
| 4 | User isolation at the data-access layer | `UserScopedRepo` (above) |
| 5 | Extract/report medical facts, never diagnose | `memory/extraction.py`, `documents/extraction.py`, `guardrails/output_check.py`'s diagnosis-language check |
| 6 | Generation behind one provider interface | `llm/base.py`/`factory.py` + the "one file owns one vendor" table above |

## Things that look wrong but are deliberate — don't "fix" these without reading why first

- **`groq_provider.py` still exists and is registered, but nothing uses it.** This is the intentional fallback-option pattern, not dead code.
- **DeepEval is a dev-dependency, never a main dependency, and is never imported outside `backend/eval/`.** This is deliberate (keeps it out of the Vercel production build and out of the live request path — it's too heavy/unpredictable-latency for a real-time guardrail). Don't move any DeepEval import into `backend/agents/` or `backend/guardrails/`.
- **The output guardrail uses word-boundary regex for allergen scanning, not a bare substring check.** A bare substring check was tried first and caused a serious bug (`"nut"` matching `"nutrition"`) — see `ISSUES_AND_FIXES.md` #34. Any new free-text safety scan should follow the same word-boundary pattern.
- **Guardrails fail open (default to "allow"), not closed, on any internal error.** This is an explicit design choice: a false positive blocking a legitimate nutrition question was judged worse than an occasional false negative, given prompt-level mitigation exists as a second layer underneath the guardrail. Don't flip this to fail-closed without discussing it — it changes the availability/safety tradeoff for the whole app.
- **`CALORIE_TOLERANCE`, `AUDIT_RETENTION_DAYS`, rate-limit thresholds, etc. are hardcoded module constants, not `Settings` fields.** This is the established convention in this codebase for tunable-but-not-meant-to-vary-by-deployment values — don't move them into `.env` just because they're numbers; only add a `Settings` field for things that genuinely need to vary per environment (an API key, a feature flag, a deployment name).
- **`backend/eval/pipeline_runner.py` manually re-implements the graph's routing logic** (calls node functions directly in sequence, replicating `_route_after_*` calls) instead of invoking the compiled graph, specifically so eval runs never touch real MongoDB. **If you change `graph.py`'s topology or routing, `pipeline_runner.py` needs the matching update** or the eval harness will silently stop exercising the real behavior. This has bitten twice already (Phase 3's memory nodes, Phase 6's guardrail nodes) — check this file whenever you touch `graph.py`.
- **`data/rag_corpus.json` is a committed file, and it must be regenerated together with any Pinecone upsert.** It's the local BM25 half of hybrid search. `backend/rag/ingest.py::ingest_pdfs()` writes both together; `rebuild_corpus_only()` exists only for corpus-only rebuilds when Pinecone is already correct. Adding a new PDF without running full `ingest_pdfs()` will silently desync the two.
- **Stochastic eval-harness failures are normal, not automatically regressions.** At `temperature=0.5`, the model occasionally undershoots the calorie target on one day out of seven, or asks a clarifying question instead of generating directly. This has been characterized repeatedly across phases (see `ISSUES_AND_FIXES.md` #26/#30) as ordinary sampling variance, confirmed by re-running the same case in isolation and seeing it pass. Before treating an eval failure as a new bug, re-run the specific case 2-3 times in isolation first.

## How to verify a change didn't break anything

1. **`uv run pytest`** — the full unit test suite (19 test files as of Phase 6), zero live API calls, zero cost, runs in CI on every push. This should always be green before you consider a change done.
2. **`uv run python -m backend.eval.runner`** — the 16-case golden-set harness against real Azure OpenAI/Pinecone (real API cost, not in CI, run manually). Deterministic checks + DeepEval judge scores; judge gates the exit code only for `rag_dependent`/`medical_context`/`allergy_diet_edge_case`. Expect some stochastic single-case noise (see above) — don't chase every red cell, but do investigate anything affecting a **safety-gated** category or a **consistent** (not one-off) failure.
3. **For anything touching the guardrails or graph topology**, hand-trace the cycle bound the way Phase 6's review did (see `ISSUES_AND_FIXES.md`'s Phase 6 section) before trusting a live run — LangGraph will raise at build time for a missing routing-map key, but it won't catch a logic error that makes a cycle unbounded.
4. **For anything touching Pinecone/RAG**, confirm `data/rag_corpus.json`'s chunk count still matches Pinecone's `describe_index_stats()` vector count for the `knowledge` namespace — they're supposed to always agree.

## Current known gaps (not bugs, just not built yet)

- No frontend UI for anything shipped since Phase 1: consent management, data export/delete, medical document upload/list/delete are all backend/API-only.
- No LangSmith account provisioned yet — tracing code exists and is wired up (Phase 6) but is off by default and has never been exercised against a live account.
- Deployment is still Vercel (interim); Phase 9 (full Azure migration) hasn't started.
- Rate-limit 429s and LangSmith trace nesting are unit-tested but not yet verified against real HTTP traffic end-to-end.
