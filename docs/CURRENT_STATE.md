# NutriBot — Current State (Phase 0 recon)

> Ground-truthed against the actual code on 2026-08-02, ahead of the v2 roadmap. Supersedes anything in `README.md` or `.env.example` where they disagree — both had drifted from the real code before this pass (see [Vercel deployment work] for the RAG/dependency corrections already made this session).

## §2 open items — resolved

| Item | Roadmap asked | Resolution |
|---|---|---|
| Vector store | FAISS or ChromaDB? | **Pinecone** (`backend/db/vector_store.py`). Migrated off local ChromaDB this session for Vercel-serverless compatibility — writes to a hosted index with integrated embedding (`llama-text-embed-v2`), namespace `"knowledge"`. This incidentally satisfies part of Phase 9's "vector store must be shared, not local-disk" requirement early. |
| Calorie math delegation | Confirm fast LLM only parses, tool does arithmetic | **Confirmed clean.** `backend/agents/calorie_agent.py` calls `backend/tools/calorie_tool.py::compute_calories()` only — zero LLM involvement. Mifflin-St Jeor BMR + activity-multiplier TDEE + goal adjustment + fixed macro-split arithmetic, all deterministic Python. Invariant #1 holds. |
| RAG fallback corpus | Confirm it exists | **Does not exist.** `backend/rag/retriever.py` returns a hardcoded string ("No clinical guidelines available…" / "temporarily unavailable") when the Pinecone index is empty or a query errors. There is no curated deterministic fallback corpus of facts to fall back to. |
| `NUTRIBOT_MAX_GENERATION_RETRIES` | Confirm it exists and is enforced | **Does not exist in code.** Referenced only in `README.md`; zero matches anywhere under `backend/`. Dead documentation — no retry cap is currently enforced anywhere in the pipeline. |

## Generation call sites — Phase 1a complete

**Status: done.** As of this pass, no agent imports a vendor SDK directly (invariant #6 satisfied). A `backend/llm/` package now owns all generation:

- `backend/llm/base.py` — `LLMProvider` ABC (`generate(messages, config) -> GenerationResult`), plus `Message`/`GenerationConfig`/`GenerationResult` Pydantic models. `GenerationConfig.profile` (`"fast"` | `"full"`) is the semantic knob callers use instead of a raw model name.
- `backend/llm/groq_provider.py` — `GroqProvider`, the only file in the codebase that imports `langchain_groq`/`ChatGroq`.
- `backend/llm/factory.py` — `get_provider()`, `@lru_cache`d, selects a provider class from a `{"groq": GroqProvider}` registry keyed on `settings.llm_provider` (default `"groq"`). This is the switch point Phase 7's `FoundryProvider` plugs into — adding it means a registry entry + a config value, zero agent-code changes.

Call sites, both now provider-agnostic:
1. **`backend/agents/intent_agent.py`** — `get_provider().generate(..., config=GenerationConfig(profile="fast", temperature=0, max_tokens=100))`. Six-way single-label classification, no tool calls.
2. **`backend/agents/meal_plan_agent.py`** — `get_provider().generate(..., config=GenerationConfig(profile="full", temperature=0.7, max_tokens=6144))`. Produces free-text response + an embedded `meal_plan_json` code block, parsed out via regex (`_extract_plan_json`). `_format_history()` now returns `list[Message]` instead of LangChain message objects.

No other agent (`profile_agent`, `calorie_agent`, `food_agent`, `rag_agent`, `memory_agent`, `email_agent`) touches an LLM — confirmed via grep, not just by naming convention.

**Urgent discovery made while smoke-testing this change (2026-08-02, unrelated to the refactor itself):** Groq fully retired both previously-configured models (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant` — gone from the account's model list entirely, not just deprecated). This broke the live production backend. Replaced with `openai/gpt-oss-120b` (full) / `openai/gpt-oss-20b` (fast) — both current Groq Production Models. These are **reasoning models**: part of the token budget goes to hidden chain-of-thought before the visible answer, which silently returned empty output at the old `max_tokens=20` for intent classification. Fixed by setting `reasoning_effort="low"` in `GroqProvider` (halves reasoning overhead, no accuracy loss observed) and raising `max_tokens` (20→100 fast, 4096→6144 full) to leave headroom. **Action still needed:** the live Vercel backend project's `LLM_MODEL`/`LLM_MODEL_FAST` env vars were set explicitly during deployment and override these code defaults — they need updating in the Vercel dashboard too, this code fix alone doesn't fix production.

**Second discovery while fixing the above:** this Groq account is on the `on_demand` (free) tier, capped at **8000 tokens/minute — a rolling per-minute rate limit shared across all requests to the account, not a per-request cap.** A single meal-plan generation request (system prompt with RAG context + food list + chat history, plus a large `max_tokens` reservation for a full 7-day JSON plan) was hitting this alone. Mitigated by trimming prompt inputs (`retrieve_with_sources` RAG cap 3000→800 chars in `backend/rag/retriever.py`; food list 30→10 items in `backend/agents/food_agent.py`; chat history 20→6 messages via `settings.chat_memory_window`, now actually wired up instead of dead config) and tuning generation (`temperature` 0.7→0.5, `max_tokens` 4096→6000 for the full profile — lower temperature reduces output-length variance too, which helps here). This makes a **single** request fit reliably. It does **not** fix the underlying shared-capacity ceiling: 3 rapid-fire test requests in a row reproduced 2/3 failures even with the trimmed config, because the limit accumulates across requests within the rolling 60s window. **Real fix is a Groq Dev Tier billing upgrade (250K TPM)** — deferred by user decision (2026-08-02), shipping the trimmed/best-effort version first. If users report intermittent "technical issue" errors on meal-plan requests, especially during back-to-back messages or concurrent usage, this is almost certainly why — check Groq's dashboard for 429/413 rate-limit errors before assuming a code bug.

**Confirmed in production after deploying:** the 413s are gone. But a second, distinct issue surfaced — `max_tokens=6000` sometimes isn't enough for the model to finish a full 7-day JSON meal plan before hitting the ceiling. The response gets cut off mid-JSON with no visible error; `_extract_plan_json` silently fails to match (no closing fence) and `plan_proposed` comes back `false` even though the user got a real (truncated) response. **Deferred by explicit user decision ("fix the token problem later")** — likely fix is raising `max_tokens` further, since the trimmed prompt leaves more headroom than 6000 currently uses (was about to test 7200 when deferred). Test with a single call, not rapid-fire, since the TPM budget is shared across requests.

## Pipeline topology

`backend/agents/graph.py` — LangGraph `StateGraph`, 6 nodes, entry at `profile`:

```
profile → intent → [route] → calorie? → rag? → food? → meal_plan → END
```

Routing (`_route_after_intent` / `_route_after_calorie` / `_route_after_rag`) is a static dict keyed on `intent`:

| Intent | Path |
|---|---|
| CALORIE_CALCULATION | calorie → meal_plan |
| MEAL_PLAN_REQUEST | calorie → rag → food → meal_plan |
| PLAN_MODIFICATION | calorie → rag → food → meal_plan |
| NUTRITION_QUESTION | rag → meal_plan |
| ROUTINE_REQUEST | rag → food → meal_plan |
| GENERAL_CONVERSATION | meal_plan (direct) |

Two more agents exist **outside the graph**, called directly from `backend/main.py`'s `/api/plans/accept` endpoint rather than as pipeline nodes: `memory_agent.save_accepted_plan` (MongoDB write) and `email_agent.deliver_plan_email` (SendGrid). This is where "8 agents" comes from — 6 graph nodes + 2 endpoint-triggered agents.

State is a single `TypedDict` (`backend/agents/state.py`, `NutriBotState`, `total=False`) threaded through every node — no per-node input/output schema validation, any node can read any prior node's output by key.

## Safety / isolation baseline

- **Food allow-list** (`backend/utils/food_filter.py::get_filtered_foods`) is a real deterministic pre-generation filter: diet-type match, allergen exclusion (absolute), medical-condition safety (`_is_condition_safe` — diabetes/hypertension/kidney-specific rules against `medical_tags` + `glycemic_index`), then ranked and capped at `limit=80`. This correctly implements invariant #3's *filtering* half.
  - **Gap:** enforcement that the LLM actually stays within the allow-list is **prompt-instruction-only** — `meal_plan_agent.py`'s system prompt says "generate ONLY from the APPROVED FOOD OPTIONS list" and "Allergy enforcement is absolute — never include allergen foods," but nothing deterministically validates the model's output against the allow-list afterward. A hallucinated or substituted food would currently ship uncaught. This is exactly the class of gap Phase 6's output-guardrail layer needs to close.
- **User isolation** (`backend/db/mongo.py`): every query/write function takes `user_id` as an explicit parameter and includes it in the Mongo filter (`{"user_id": user_id, ...}`), consistently, across users/sessions/plans. **But there is no single centralized data-access layer or wrapper enforcing this structurally** — it's currently upheld by consistent convention in every function, not by a choke point that would make a missing filter impossible to write. Matches Phase 2's framing exactly: this needs to become a structural guarantee, not a convention.
- **JWT auth** (`backend/auth/jwt_handler.py`) gates every `/api/*` route via `Depends(get_current_user_id)`; route handlers additionally check `payload.user_id != user_id` (e.g. `chat_message`, `accept_plan` in `backend/main.py`) as a belt-and-suspenders check against a caller passing someone else's `user_id` in the request body.

## Testing

`tests/` exists but is **empty** — zero test files. Phase 1c's test-coverage gate (calorie_tool branches, food-filter allergen/diet exclusion) has not started.

## Deployment / infra (as of this session, interim per the v2 roadmap decision — see roadmap doc)

- **Backend**: FastAPI (`backend/main.py`), deployed to Vercel serverless via `[tool.vercel] entrypoint = "backend.main:app"` in `pyproject.toml`. Live at `https://nutribot-backend-xi.vercel.app`.
- **Frontend**: Next.js 15, deployed to Vercel. Live at `https://nutribot-frontend-delta.vercel.app`.
- **DB**: MongoDB Atlas (`motor`, async), collections currently in use: `users`, `chat_sessions`, `accepted_plans` — not yet the full Phase 2 schema (`profiles`, `conversations`, `messages`, `memories`, `medical_reports`, `medical_facts`, `medical_events`, `meal_plans` don't exist yet).
- **Vector store**: Pinecone, as above.
- **LLM**: Groq only (via `backend/llm/`), models `openai/gpt-oss-120b` / `openai/gpt-oss-20b`, no fallback provider yet (Phase 7 item).
- **Secrets**: plain env vars via `pydantic-settings`, no boot-time validation against defaults, no Key Vault (Phase 1c / Phase 9 items, not yet started).
- **Roadmap decision**: Azure remains the Phase 9 target; Vercel is explicitly interim, not a redirection of the roadmap.

## What Phase 0 leaves open

Everything under §4 of the roadmap (Foundry serverless-vs-dedicated, reranker model/placement, judge coverage thresholds, retention windows, RAG-mode disclosure) is still undecided — none of it is inferable from the current code, all of it is a Phase 5–7 decision.

## Phase 1b — evaluation harness (done, 2026-09-03)

`backend/eval/` — golden set (16 cases, 2 per roadmap category, `backend/eval/golden_set.py`), a pipeline runner that exercises the real agent nodes without touching MongoDB (`backend/eval/pipeline_runner.py`, reuses `_format_profile_context` and the real routing predicates from `backend/agents/graph.py` rather than reimplementing them), a deterministic scorer (`backend/eval/scorers/deterministic.py`) and an LLM-judge stub (`backend/eval/scorers/judge.py`, non-gating). Run via `python -m backend.eval.runner`; writes `eval_results.json`; exits non-zero on any deterministic failure (verified both exit paths). Paced with a 5s inter-case delay against the shared Groq TPM budget.

**First real run (9/16 passed) already surfaced three distinct, previously-unmeasured issues** — this is the harness doing its job:
1. **Confirms the already-known JSON-truncation issue is frequent, not rare.** 4/16 cases (25%) got `plan_proposed=False` when a plan was expected — the same `max_tokens=6000` truncation issue found in production testing (see the rate-limit mitigation entry above), now with a measured frequency instead of an anecdotal "it happened once."
2. **New finding: generated plans frequently undershoot the calorie target substantially**, not just outside the ±15% tolerance band but by 30-65% in several cases (e.g. `mpr-02`: 1184-1287 kcal/day vs a goal of 3339). This is distinct from the truncation issue (these cases completed with a full valid JSON plan, just calorically wrong) and wasn't visible before this harness existed.
3. **New finding: confirms the food-allow-list-enforcement gap flagged in the original Phase 0 recon is real, not theoretical** — case `pm-02` included "Turkey breast" in the generated plan, which was not in the `food_context` list actually offered to the model for that request. Direct evidence for the Phase 6 guardrail work.

None of these three were fixed as part of 1b (harness scope is measurement, not remediation) — they're now tracked, reproducible findings for whoever picks up Phase 1c/6 next, instead of suspected-but-unverified gaps.

## Findings #2 and #3 — fixed (2026-09-03)

**#2 (calorie undershoot) root cause confirmed and fixed:** `backend/utils/food_filter.py::get_filtered_foods` ranked purely by `(low-GI-first, highest-protein)` and truncated to `limit`, which for a non-vegetarian profile produced a **100% protein-dominant** top-10 (chicken/turkey/fish/protein powder) — summing all 10 once capped out around 2010 kcal, nowhere near a 3339 kcal muscle-gain target, even though the 123-food DB has plenty of carb/fat range (82 carb-dominant, 26 fat-dominant foods, including items up to 360 kcal). Fixed by selecting across protein/carb/fat pools proportionally to `calorie_tool.py`'s existing `DEFAULT_MACRO_SPLIT` (30/40/30) instead of one flat sort — verified (pure Python, deterministic): the same profile now gets a 3/4/3 macro split, raising the single-serving calorie ceiling to 2329 kcal, and a diabetic profile is still confirmed 100% low-GI (no regression). Also added a prompt instruction (`backend/agents/meal_plan_agent.py`) permitting the model to scale an approved food beyond its default serving with proportionally recalculated macros — **confirmed working in a live response** (chicken breast correctly scaled 150g/248kcal → 200g/331kcal, exact proportional math) — and loosened the unrealistic "±50 kcal" prompt instruction to "within 10%".

**#3 (food allow-list violation) confirmed to be a mix of both a scorer bug and a real gap:** added `food_name_matches()` (`backend/utils/food_filter.py`) — tolerant matching (strips parenthetical qualifiers, substring-tolerant) shared by both the eval scorer and a new production enforcement step, `_sanitize_plan()` in `backend/agents/meal_plan_agent.py`, which now runs after every successful JSON extraction and **deterministically strips any item that doesn't match an approved food, recomputing totals from what's left** — the first actual enforcement of invariant #3 ("model may only select from the list"), not just a prompt instruction. Verified via unit test with a synthetic plan (kept a fuzzy-matched real item, correctly stripped an invented one, correct recomputed totals).

**Not fully verified end-to-end**, and worth knowing: three separate attempts to reproduce a full live meal-plan generation for a before/after comparison **all hit the pre-existing, already-deferred JSON-truncation issue** (`max_tokens` ceiling reached before the plan finished) rather than completing. Re-examining the original Phase 1b run: the true rate for cases that actually need a full plan is ~50% (4 of 8), not the 25%-of-16 stated above — worse than previously characterized. The new scaling-instruction prompt addition is a few dozen tokens longer and asks the model to do slightly more per item (decide + recompute a scaled quantity), which is a plausible (unconfirmed) contributor to output length — worth watching, not yet proven. **Recommended next step: run `python -m backend.eval.runner` for a full before/after scorecard** — deferred here rather than run automatically, since it's another ~16 real API calls against the same constrained account.

## Phase 1c — hardening (scoped subset done, 2026-09-03)

Per user decision, this session covers secrets boot-guard, structured logging/trace_id, Docker + CI, and the safety-critical test suite — **rate limiting on `/api/chat` and login brute-force protection are explicitly deferred**, bundled with the already-deferred Groq rate-limit issue until the planned move to Azure OpenAI.

- **Secrets boot-guard**: `backend/config.py` gains `environment` (`development`/`staging`/`production`, default `development`). `backend/main.py::_validate_production_secrets` raises `RuntimeError` at import time when `environment=="production"` and `JWT_SECRET`/`MONGODB_URI` (localhost)/`GROQ_API_KEY`/`PINECONE_API_KEY` are missing or default-insecure — verified both the failing and passing paths locally. **The live Vercel backend project does not yet have `ENVIRONMENT=production` set** — this is a manual step for the user; Vercel MCP access is no longer available in this session to set it directly.
- **Structured logging + trace_id**: new `backend/observability.py` — a `contextvars`-based `trace_id_var` + logging `Filter` + JSON `Formatter`, wired in via `configure_logging()` (replaces `logging.basicConfig`). This means **every existing `logger.*` call across all 8 agents automatically gets a `trace_id`** without any of those call sites being touched — verified with a direct test (before/after `trace_id_var.set()`). `NutriBotState` gained a `trace_id` field, seeded in `run_chat_pipeline`; `backend/main.py`'s `/api/chat/message` handler sets a fresh trace_id per request.
- **Docker**: root `Dockerfile` (single-service, `python:3.12-slim` + `uv`) and `docker-compose.yml`, aimed at local dev parity and Phase 9's eventual Azure Container Apps target — **not build-verified in this session** (Docker CLI present but the daemon wasn't running; code-reviewed only, flagged rather than silently assumed working). `main.py`'s `uvicorn.run(reload=...)` is now conditional on `environment == "development"`.
- **CI**: `.github/workflows/ci.yml` runs `uv sync --dev && uv run pytest -v` on push/PR to `master`. Deliberately excludes the eval harness (real API cost + shared Groq rate-limit risk on every commit is the wrong tradeoff for an auto-triggered gate) — the harness stays a manually-run tool.
- **Tests**: `tests/test_calorie_tool.py` (21 cases: every activity multiplier, every goal adjustment, both gender branches, diabetes/PCOS macro override including both-at-once, case-insensitivity, unrecognized-value fallbacks) and `tests/test_food_filter.py` (12 cases: allergen exclusion, diet-type filtering, all three medical-condition safety branches, the macro-diversity selection fix as an explicit regression test, and `food_name_matches`). All 33 pass. Needed a `[tool.pytest.ini_options] pythonpath = ["."]` addition to `pyproject.toml` — `tests/` has no `__init__.py`, so nothing added the repo root to `sys.path` for `backend.*` imports otherwise.

Environment separation beyond the `environment` setting (e.g. separate `.env.staging`/`.env.production` files) was intentionally not built — Vercel already scopes env vars per-environment (Production/Preview/Development) natively in its dashboard, so a file-based split doesn't fit how this app is actually deployed.
