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
