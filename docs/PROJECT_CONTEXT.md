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

NutriBot is an AI nutrition assistant: a FastAPI backend running a 10-node LangGraph agent pipeline (input safety check → profile → memory retrieval → intent classification → calorie math → RAG retrieval → food filtering → meal plan generation → output safety check → memory extraction), backed by MongoDB Atlas (user data), Pinecone (hybrid-search RAG over clinical guideline PDFs), Azure OpenAI (generation), and Azure Speech + Translator (voice input and per-message multilingual chat, translated at the edges so the pipeline itself only ever sees English). A Next.js frontend (light neubrutalist redesign, 2026-09-13) covers chat (plain and SSE-streamed), profile create/edit (incl. renaming the bot and choosing spoken languages), medical document upload/list/delete, delete-chat-session, and the mic; consent is handled inside the profile form. Account-level export/delete remain backend/API-only. Phases 0-7 of a 10-phase roadmap are done, Phase 8 skipped, plus a substantial post-Phase-7 latency/UX/deployment pass (see `docs/ROADMAP.md`). **Deployed and current on Vercel as of 2026-09-29.**

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

**Two ways to invoke the same pipeline** (added 2026-09-13): `run_chat_pipeline()` (`graph.ainvoke`, used by `POST /api/chat/message`) and `stream_chat_pipeline()` (`graph.astream(stream_mode="updates")`, used by `POST /api/chat/message/stream`) — the latter yields a progress event after every node completes, keyed by the LangGraph-assigned node name (`NODE_PROGRESS_LABELS` in `graph.py` maps node names to the user-facing label shown in the frontend's typing indicator). **This is real per-stage progress, not a fake timer or token-level streaming** — see the "SSE streaming" entry below for why token streaming isn't safe here. Both entry points compile the same singleton graph; adding a node only requires updating `NODE_PROGRESS_LABELS` if you want a friendly label (an unmapped node falls back to its raw name, it doesn't break).

### Directory map (`backend/`)

| Directory | Owns |
|---|---|
| `agents/` | The 10 LangGraph nodes + `state.py` (shared state shape) + `graph.py` (topology/routing) + `plan_builder.py` (pure: model selection → fully computed plan, invariants 1/2) |
| `guardrails/` | Runtime input/output safety checks (Phase 6) — `input_check.py`, `output_check.py`, `nodes.py` (LangGraph adapters), `models.py` |
| `llm/` | The `LLMProvider` abstraction (`base.py`), `factory.py` (`get_provider()` registry), one file per vendor (`azure_openai_provider.py`, `groq_provider.py`) |
| `rag/` | Retrieval: `retriever.py` (the hybrid pipeline), `bm25_index.py`, `fusion.py`, `reranker.py`, `ingest.py` (PDF → Pinecone + local corpus) |
| `documents/` | Medical document upload pipeline (Phase 4) — `blob_storage.py`, `doc_intelligence.py`, `extraction.py`, `validation.py` |
| `memory/` | Long-term semantic memory extraction (Phase 3, chat-turn-based; distinct from `documents/extraction.py`, which extracts from uploaded files) |
| `context/` | `builder.py::build_context()` — assembles a `GenerationContext` from state for prompt-building, the single place that replaced ad hoc `state.get(...)` scattered through prompt code |
| `db/` | `mongo.py` (`UserScopedRepo`, the user-isolation layer, + `ensure_indexes()`), `vector_store.py` (Pinecone client) |
| `security/` | `rate_limit.py` — Mongo-backed rate limiting (Phase 6) |
| `speech/` | Voice + multilingual: `token.py` (Azure Speech tokens), `translation.py` (Azure Translator), `multilingual.py` (translate-at-the-edges orchestration around the chat endpoint), `locales.py` (per-user "languages I speak" validation) |
| `eval/` | The offline evaluation harness — golden set, pipeline runner (real node functions, no MongoDB), deterministic + DeepEval scorers |
| `tools/` | `calorie_tool.py` (the ONLY place BMR/TDEE/macro math happens — invariant 1), `email_tool.py`, `pdf_tool.py` (plan → PDF, numbers verbatim from the computed plan) |
| `utils/` | `food_filter.py` (the pre-generation allow-list — invariant 3) |
| `models/` | Pydantic request/response/DB schemas, one file per domain |
| `auth/` | JWT + Google OAuth |
| `observability.py`, `config.py`, `main.py` | Cross-cutting: logging/tracing, settings, the FastAPI app itself |

### "One file owns one external service" — the current full list

This pattern (invariant 6) means: if you need to call a vendor SDK, find the file that already owns it, or create a new dedicated one — never call a vendor SDK inline from an agent, guardrail, or anywhere else.

| Vendor / concern | Owning file |
|---|---|
| Azure OpenAI generation (primary, `azure_openai`) | `backend/llm/azure_openai_provider.py` |
| Azure OpenAI challenger (`azure_openai_challenger`, Phase 7 — eval-only until promoted) | same class/file, registered a second time with different deployments in `backend/llm/factory.py` |
| Groq generation (fallback provider, not currently active) | `backend/llm/groq_provider.py` |
| Azure Blob Storage | `backend/documents/blob_storage.py` |
| Azure Document Intelligence | `backend/documents/doc_intelligence.py` |
| Pinecone | `backend/db/vector_store.py` (client), `backend/rag/retriever.py` (queries) |
| In-process BM25 | `backend/rag/bm25_index.py` |
| DeepEval's judge LLM | `backend/eval/deepeval_provider.py` (routes back through `get_provider()` — DeepEval itself never gets its own vendor credentials) |
| MongoDB | `backend/db/mongo.py` |
| SendGrid | `backend/tools/email_tool.py` |
| Google OAuth | `backend/auth/google_oauth.py` |
| ReportLab (meal-plan PDF rendering) | `backend/tools/pdf_tool.py` |
| Azure Speech (token minting only — recognition runs in the browser) | `backend/speech/token.py` |
| Azure Translator (REST v3) | `backend/speech/translation.py` |

**Any brand-new external dependency gets its own file, following this same shape**: a thin wrapper with no business logic, business logic (auth checks, user scoping, validation) stays in the caller.

### The provider abstraction (why you can swap LLM vendors without touching agents)

`backend/llm/base.py` defines `Message`, `GenerationConfig` (`profile: "fast"|"full"`, `temperature`, `max_tokens`), `GenerationResult`, and the `LLMProvider` ABC (`async generate(messages, config) -> GenerationResult`). Every agent, guardrail, and eval scorer calls `get_provider().generate(...)` — never a vendor SDK directly. `backend/llm/factory.py::get_provider(name=None)` is `@lru_cache`d and picks a provider *builder* from a registry. With no argument it resolves `settings.llm_provider` (what every agent does); with an explicit name it pins that entry regardless of the active provider (used to pin the eval judge and to drive `--compare` arms). **This is exactly how the Groq → Azure OpenAI migration happened as a registry addition instead of an agent-by-agent rewrite, and how Phase 7's challenger landed as a third entry** — `AzureOpenAIProvider` is parameterized (deployments, a `reasoning_model` flag, a provider name) and registered twice against the same resource. Cache caveat: the zero-arg entry snapshots `llm_provider` at first use, so anything that mutates it (compare mode, tests) must call `get_provider.cache_clear()`.

**Currently active**: `LLM_PROVIDER=azure_openai` (`.env`, and confirmed live in Vercel production as of 2026-09-29 — see `docs/ISSUES_AND_FIXES.md` #55, production had actually been silently running on Groq until this was caught), deployment `gpt-5-mini-1` for both `fast` and `full` profiles. Groq stays registered as a fallback option, not deleted — if you ever flip `LLM_PROVIDER=groq` back on, **the token budgets need lowering again** (see the "if Groq is reactivated" notes throughout `CURRENT_STATE.md` — `max_tokens`, food list size, RAG context cap, and chat history window were all raised for Azure's much higher quota and will cause truncation again under Groq's 8000 TPM ceiling).

**`FAST_CALL_PROVIDER` (added 2026-09-13, default empty)**: a second, orthogonal pinning knob from Phase 7's `get_provider(name)` — `intent_agent.py`, `guardrails/input_check.py`, and `guardrails/output_check.py`'s LLM half all call `get_provider(settings.fast_call_provider or None)` instead of the zero-arg form, so these three small classification/safety calls can be routed to a faster non-reasoning model (`azure_openai_challenger`) independently of what `llm_provider` the actual generation calls use. Empty (default) = identical to before, all calls share `llm_provider`. **This setting has a real dependency**: setting it to `azure_openai_challenger` without that provider's own deployment vars configured breaks intent classification *and* the input guardrail for every message, silently (`docs/ISSUES_AND_FIXES.md` #56) — verify the challenger resolves before pinning anything to it.

**Reasoning vs. classic models are handled by an explicit flag, never by parsing the deployment name.** `azure_openai_reasoning_model` (primary, default `True` for gpt-5-mini) and `azure_openai_challenger_reasoning_model` (default `False` for gpt-4.1) select the kwargs branch: reasoning models get `reasoning_effort` and no `temperature`, classic models get `temperature` and no `reasoning_effort` — each rejects the other's parameter. Promoting a classic model to primary means pointing the primary deployments at it **and** flipping the flag to `false`; forgetting the flag produces 400s.

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
| 1 | LLM never does deterministic math | `backend/tools/calorie_tool.py::compute_calories()` for targets (`calorie_agent.py` calls only this) and `backend/agents/plan_builder.py::build_plan()` for the plan itself (per-item nutrients, meal/day totals, portion rescaling). The model only picks foods and grams. Until 2026-09-12 the model wrote per-item calories and the agent summed them — that was the real cause of the long-running "calorie drift" failures |
| 2 | `food_db.json` is the sole macro source of truth | `backend/utils/food_filter.py` reads it; `plan_builder.py` computes every plan number as `db_value × grams ÷ quantity_grams`; `eval/scorers/deterministic.py` re-checks that equality on every item |
| 3 | Safety via pre-generation allow-list | `get_filtered_foods()` (pre-gen filter) + `plan_builder.py::build_plan()` (post-gen: off-list selections are dropped via `find_food()` before any nutrient is computed) + `guardrails/output_check.py` (prose-level check, Phase 6) |
| 4 | User isolation at the data-access layer | `UserScopedRepo` (above) |
| 5 | Extract/report medical facts, never diagnose | `memory/extraction.py`, `documents/extraction.py`, `guardrails/output_check.py`'s diagnosis-language check |
| 6 | Generation behind one provider interface | `llm/base.py`/`factory.py` + the "one file owns one vendor" table above |

## Things that look wrong but are deliberate — don't "fix" these without reading why first

- **`groq_provider.py` still exists and is registered, but nothing uses it.** This is the intentional fallback-option pattern, not dead code.
- **DeepEval is a dev-dependency, never a main dependency, and is never imported outside `backend/eval/`.** This is deliberate (keeps it out of the Vercel production build and out of the live request path — it's too heavy/unpredictable-latency for a real-time guardrail). Don't move any DeepEval import into `backend/agents/` or `backend/guardrails/`.
- **The output guardrail uses word-boundary regex for allergen scanning, not a bare substring check.** A bare substring check was tried first and caused a serious bug (`"nut"` matching `"nutrition"`) — see `ISSUES_AND_FIXES.md` #34. Any new free-text safety scan should follow the same word-boundary pattern.
- **Guardrails fail open (default to "allow"), not closed, on any internal error — with one narrow, deliberate exception.** This is an explicit design choice: a false positive blocking a legitimate nutrition question was judged worse than an occasional false negative, given prompt-level mitigation exists as a second layer underneath the guardrail. Don't flip this to fail-closed without discussing it — it changes the availability/safety tradeoff for the whole app. **The one exception**: `ContentFilterBlocked` (`backend/llm/base.py`) is caught *before* the generic exception handler in `input_check.py` and fails **closed** for `self_harm`/`violence` categories specifically — because that exception means Azure's own content filter actively confirmed a violation, not that something broke. "The call failed" (fail open) and "the vendor confirmed this is unsafe" (fail closed) are different situations; don't conflate them if you touch this again.
- **The output guardrail's allergen scan does not have absolute veto power over the LLM's judgment — only when the LLM call itself fails.** Originally a deterministic hit unconditionally forced `safe=False`; live testing (`docs/ISSUES_AND_FIXES.md` #58) found this blocking nearly every real answer for a milk-allergic user, since a word-proximity scan can't distinguish "eat milk" from "milk-derived ingredients, check labels." The LLM check is now given the user's allergy list and an explicit rubric item to adjudicate the scan's findings; its verdict is trusted when the call succeeded, and the scan alone remains the fail-closed fallback only when the LLM call errors out. If you're tempted to "simplify" this back to an unconditional deterministic veto, re-read #58 first — that was the original design, and it was the bug.
- **The eval judge is pinned to `eval_judge_provider` (default `azure_openai`), not to the active `llm_provider`.** In `--compare` mode the active provider is swapped to the challenger for one arm; if the judge followed it, the challenger would be judging its own output and the two arms wouldn't be comparable. Don't "simplify" `deepeval_provider.py` back to a zero-arg `get_provider()`.
- **`CALORIE_TOLERANCE`, `AUDIT_RETENTION_DAYS`, rate-limit thresholds, etc. are hardcoded module constants, not `Settings` fields.** This is the established convention in this codebase for tunable-but-not-meant-to-vary-by-deployment values — don't move them into `.env` just because they're numbers; only add a `Settings` field for things that genuinely need to vary per environment (an API key, a feature flag, a deployment name).
- **`backend/eval/pipeline_runner.py` manually re-implements the graph's routing logic** (calls node functions directly in sequence, replicating `_route_after_*` calls) instead of invoking the compiled graph, specifically so eval runs never touch real MongoDB. **If you change `graph.py`'s topology or routing, `pipeline_runner.py` needs the matching update** or the eval harness will silently stop exercising the real behavior. This has bitten twice already (Phase 3's memory nodes, Phase 6's guardrail nodes) — check this file whenever you touch `graph.py`.
- **`data/rag_corpus.json` is a committed file, and it must be regenerated together with any Pinecone upsert.** It's the local BM25 half of hybrid search. `backend/rag/ingest.py::ingest_pdfs()` writes both together; `rebuild_corpus_only()` exists only for corpus-only rebuilds when Pinecone is already correct. Adding a new PDF without running full `ingest_pdfs()` will silently desync the two.
- **Meal-plan generation is two LLM calls with deterministic code between them, and the plan text is rendered by code.** `meal_plan_agent.py::_plan_turn`: selection (JSON of foods + grams, temperature 0.2) → `plan_builder.build_plan()` → prose (the message *around* the plan). The response the user sees is `prose + render_plan_markdown(plan) + ACCEPT_PROMPT`, assembled by code. Don't "simplify" this back to one call that writes the table itself: that is exactly the design that produced 16-34% calorie undershoots on every day across two models (`ISSUES_AND_FIXES.md` #39/#40). The extra call is the price of numbers that are always right and prose that can never disagree with the card.
- **`plan_builder.py` rescales an off-target day's portions by one uniform factor, clamped to [0.6, 1.75].** If a day is still outside ±10% after that, it's left off-target and reported (`PlanBuildReport.off_target_days`), never silently forced. A clamp hit means the model's picks were wrong for the target (or the food list can't reach it) — look at the report line the eval runner prints per case before touching the clamp.
- **The food list handed to the model is 40 items, selected per meal slot, with carb/fat pools ranked by calorie density.** `tests/test_food_filter.py` asserts for every golden profile that each slot has ≥8 options and the list can physically reach the target. A "simpler" protein-first selection is what starved breakfasts and snacks (#39). Adding foods to `food_db.json` goes through this selection — more DB entries alone don't change what the model sees.
- **Multilingual is translate-at-the-edges, not "ask the LLM to reply in Hindi".** `backend/speech/multilingual.py` translates the incoming message to English before `run_chat_pipeline` and the reply back after; the pipeline, every guardrail, food matching, memory extraction and the eval harness only ever see English. Asking the model to answer in the user's language directly would silently bypass the English-only deterministic checks (the allergen-in-prose scan looks for English words). The language is decided **per message** (a speech locale hint is authoritative; typed text is auto-detected; short all-ASCII messages and low-confidence detections are assumed English), it fails open to English at every step, and on a plan turn only the prose and accept prompt are translated -- the rendered table is kept verbatim (`response_parts` in state exists for this; `_split_response` refuses stale parts). Stored messages carry both `content` (user's language) and `content_en`; `format_history` feeds `content_en` back. Don't add a language field to the LLM prompts.
- **The Speech key never reaches the browser.** `GET /api/speech/token` mints a 10-minute token; recognition happens client-side with the Speech SDK (`frontend/src/services/speech.ts`, loaded lazily). The candidate locales on that response are the user's `spoken_languages` (max 4, one per language -- Azure's at-start language-ID limits, enforced in `backend/speech/locales.py`) or the server default. TTS is deliberately out of scope (user decision).
- **Meal-plan day count is parsed *and* enforced, not just prompted.** `_requested_day_count()` (`meal_plan_agent.py`) regex-parses "N day(s)" out of the user's message (default 7, clamped to `plan_builder.MAX_DAYS`), and the selection's resulting `days` list is truncated to that count after parsing — the same "don't trust the model on a number that matters" pattern as invariant 1. Was previously hardcoded to 7 in five separate places in the prompt with no parsing at all (`docs/ISSUES_AND_FIXES.md` #49).
- **A cheat day only ever gets treat-tagged foods when explicitly requested, and only within existing safety filters.** `food_filter.get_filtered_foods(include_treats=True)` is the sole gate on treat-tagged items ever appearing in the model's approved-food list — default `False`, so a normal week can never surface pizza or ice cream. When `True`, treat items still go through the exact same allergen/diet-type/medical-condition filtering as everything else, **including the absolute low-GI rule for diabetes/PCOS** — a cheat day relaxes food *purity* (whole-food vs. treat), never a safety constraint. This means a diabetic/PCOS user requesting a cheat day may get *zero* treat options (every current treat is glycemic_index=high); `meal_plan_agent.py`'s prose prompt is told to explain this gracefully rather than silently produce a normal plan while claiming it's a cheat day. Cheat-day *detection* (`wants_cheat_day_in_conversation()`) scans the whole conversation's user turns, not just the current message, so it stays active across a modification without the user repeating "cheat day" every turn (`docs/ISSUES_AND_FIXES.md` #53).
- **Memory retrieval reserves a quota for `medical_history` facts; it isn't one flat recency cutoff.** `get_active_memories()` fills up to `medical_limit` (default 3) slots from `medical_history` facts by recency, then fills the rest of `limit` (default 5) from every other category by recency — so a document-extracted medical fact can't be silently pushed out of context by a few newer chat preferences (`docs/ISSUES_AND_FIXES.md` #50). `_format_memory_context()` groups the two under separate prompt headings for the same reason (clarity for the model, not just retrieval).
- **`/api/chat/message/stream` streams pipeline *stage progress*, deliberately not raw model tokens.** The output guardrail needs a complete response before it can pass or reject it, and a meal-plan turn is two sequential LLM calls with deterministic code in between — there's no single in-progress token stream that's ever safe or meaningful to show the user directly (a partial sentence could be about to get regenerated or replaced with a fallback). `stream_chat_pipeline()` (`graph.py`) yields a progress event after each LangGraph node completes instead — real stage completions, not a fake timer — then one `done` event with the exact same payload `/api/chat/message` returns. Don't build token-level streaming on top of this without first solving how the guardrail would work against a stream it can't fully see yet.
- **Stochastic eval-harness failures still happen, but calorie-target misses are no longer one of them.** At `temperature=0.5` the model may still ask a clarifying question instead of generating (the selection call's JSON-only shape makes this rare), or the judge may score a borderline response differently run to run. A day outside ±15% of target is now a *deterministic* failure with a code cause (the builder reports it) — treat it as a bug, not noise. Before treating any other eval failure as a new bug, re-run the specific case 2-3 times in isolation first.

## How to verify a change didn't break anything

1. **`uv run pytest`** — the full unit test suite (421 tests, 35 files as of 2026-09-16), zero live API calls, zero cost, runs in CI on every push. This should always be green before you consider a change done. For the frontend, `./node_modules/.bin/tsc --noEmit -p .` in `frontend/` is the equivalent gate.
2. **`uv run python -m backend.eval.runner`** — the 19-case golden-set harness against real Azure OpenAI/Pinecone (real API cost, not in CI, run manually; ~35-45 min). Deterministic checks + DeepEval judge scores; judge gates the exit code only for `rag_dependent`/`medical_context`/`allergy_diet_edge_case`. Each plan case also prints a `plan:` line — the per-day calories and how many days `plan_builder` had to rescale, by what factor. Rebalance factors drifting toward the 1.75 clamp, or any `OFF-TARGET`, means the model's picks or the food list need attention even if the case passed. Expect some stochastic judge noise (see above) — don't chase every red cell, but do investigate anything affecting a **safety-gated** category or a **consistent** (not one-off) failure.
2b. **`uv run python -m backend.eval.runner --compare`** — the same golden set on the primary and challenger arms with a pinned judge, plus a `promotable` verdict (Phase 7). It probes the challenger with one tiny live call first, so a misconfigured or not-yet-created deployment fails in seconds instead of after the full primary arm. Single runs are noisy — run it 2-3 times and require a consistent verdict before promoting.
3. **For anything touching the guardrails or graph topology**, hand-trace the cycle bound the way Phase 6's review did (see `ISSUES_AND_FIXES.md`'s Phase 6 section) before trusting a live run — LangGraph will raise at build time for a missing routing-map key, but it won't catch a logic error that makes a cycle unbounded.
4. **For anything touching Pinecone/RAG**, confirm `data/rag_corpus.json`'s chunk count still matches Pinecone's `describe_index_stats()` vector count for the `knowledge` namespace — they're supposed to always agree.

## Current known gaps (not bugs, just not built yet)

- Frontend gap: account-level data export/delete (`GET /api/user/export`, `DELETE /api/user/account`) is still backend/API-only. (Profile edit, bot rename, consent, voice input/spoken-language selection, medical documents, and delete-chat-session all now have UI.)
- **Voice input and translation are now live-verified** (2026-09-13/29, an Azure AI services resource was provisioned): `GET /api/speech/token` returns a real token in production, a Hindi round-trip through `/api/chat/message` returns `language`/`message_english` correctly, and continuous recognition (not `recognizeOnceAsync`) is live in the browser (`docs/ISSUES_AND_FIXES.md` #51). Still only spot-checked in Chrome; a non-Chrome browser check remains open.
- No LangSmith account provisioned yet — tracing code exists and is wired up (Phase 6) but is off by default and has never been exercised against a live account.
- The gpt-4.1 challenger (`gpt-4.1-1`) was evaluated live in Phase 7 and came out at parity with gpt-5-mini (13/16 each, no safety regressions) — **deliberately not promoted for full generation** (parity at roughly 4-8× the per-token cost). It **is** now used for the three small classification/safety calls via `FAST_CALL_PROVIDER` (2026-09-13, see above), which is a different, cheaper use than full plan generation and was not blocked by the parity finding. Whether to also promote it for meal-plan generation itself (the dominant remaining latency source) is an open, not-yet-decided question.
- **Deployment is current on Vercel** (2026-09-29) — code and environment variables both verified live and matching local `.env`/`master` (`docs/ISSUES_AND_FIXES.md` #54-#56). Still interim per the roadmap; Phase 9 (full Azure migration) hasn't started.
- Rate-limit 429s and LangSmith trace nesting are unit-tested but not yet verified against real HTTP traffic end-to-end.
- A setting that pins a call to a named provider (`FAST_CALL_PROVIDER`, `LLM_PROVIDER`) doesn't validate that provider's own config at settings-load time — a misconfigured target only surfaces per-call, via the generic exception handler, with no startup-time error (`docs/ISSUES_AND_FIXES.md` #56). A candidate follow-up, not yet done.
