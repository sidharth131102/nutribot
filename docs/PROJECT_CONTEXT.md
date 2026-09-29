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

---

# Explaining this project to an interviewer

> **Different audience from everything above.** Everything above this line is written for an engineer (or AI agent) about to *change code* — terse, assumes you're reading the source alongside it. This section is written for *you*, to talk through out loud, with no code open. It repeats some facts from above on purpose (so you don't have to cross-reference mid-sentence) and adds framing, "why," and concrete numbers that make for a good spoken answer. Skim the whole thing once; the "numbers cheat sheet" and "three stories" at the end are the fastest to re-read right before a call.

## The 30-second pitch

NutriBot is an AI nutrition assistant — a conversational app that builds personalized, medically-aware meal plans. The interesting engineering isn't the chatbot part, it's that it's a **multi-agent pipeline with hard safety and correctness guarantees around a non-deterministic LLM**: the model never does arithmetic that ends up in front of a user, every generated response is deterministically checked before and after generation for a specific set of safety properties (allergens, medical claims, self-harm), and every piece of personal data is isolated at the data-access layer, not by convention. It's built like a system that has to be trustworthy for a domain (health/medical data) where a wrong or hallucinated answer is a real problem, not a system that happens to call an LLM.

## Why this is interesting beyond "it calls an LLM"

If someone asks "what's hard about this," the honest answer isn't the LLM integration itself — that's a few lines of code behind an abstraction. What's hard, and what most of the actual engineering time went into, is:

1. **Trusting a non-deterministic component for the parts of the system that must be deterministic.** A meal plan has numbers in it — calories, grams, macros — that a user (or their doctor) might actually rely on. The design answer was: never let the model produce a number that's shown to the user. The model *chooses* (which foods, roughly how much); code *computes* (every gram → every calorie, from a database, in Python). This sounds obvious in the abstract but took real iteration to get right in practice (see the "calorie drift" story below).
2. **Safety enforcement that can't be bypassed by a clever prompt.** Allergen exclusion isn't "the system prompt says don't suggest peanuts to a peanut-allergic user" — it's a pre-generation filter that removes peanut-containing foods from the list the model is even shown, *plus* a post-generation scan of the free-text response, *plus* an LLM-based semantic check, three independent layers, because any single layer (especially "ask the model nicely") is not something you'd want to be the only thing standing between a real allergy and a real answer.
3. **Iterating on a live system with real safety trade-offs and no do-overs.** Several of the most consequential fixes in this project came from live production testing catching things unit tests structurally can't — a guardrail blocking its own correct answer, a config gap that silently degraded a safety check for every user. Being able to talk through *how* those were found and fixed (not just that they were) is good interview material — see "three stories" below.

## System architecture — the 60-second version

```
Browser (Next.js)
   │  HTTPS (JWT bearer token)
   ▼
FastAPI backend (single process, ASGI, deployed as Vercel serverless functions)
   │
   ├─ Auth: JWT + Google OAuth2
   ├─ MongoDB Atlas — user data, chat history, memory, consent/audit logs
   ├─ Pinecone — vector search over clinical-guideline PDFs (hosted, serverless index)
   ├─ Azure OpenAI — the LLM (two deployments: a reasoning model as primary, a classic
   │   model pinned to cheap classification calls)
   ├─ Azure Blob Storage + Document Intelligence — uploaded medical documents, OCR'd
   ├─ Azure Speech + Translator — voice input, multilingual chat
   └─ The LangGraph agent pipeline — a 10-node stateful graph that's the actual
      "brain": every chat message runs through it start to finish before a response
      goes back to the browser
```

**One request, end to end** (a user sends a chat message): browser POSTs to `/api/chat/message` (or the streaming variant) with a JWT → FastAPI validates the token and loads the user → the message is translated to English if needed → the LangGraph pipeline runs (below) → the response is translated back to the user's language if needed → both sides of the turn are written to MongoDB → the response goes back to the browser. Every step after "validate the token" happens inside one function call (`run_chat_pipeline` or its streaming twin) — there's no message queue, no background worker, nothing async-and-detached in the middle. It's a normal synchronous request/response cycle; the "agent" framing is about how that one function is internally structured, not about distributed execution.

## The agent pipeline, node by node — what and why

This is a **LangGraph `StateGraph`**: think of it as a flowchart where each box is a function that reads and writes a shared state dict, and edges (some conditional, based on what the box decided) determine where execution goes next. Compiled once at startup, invoked per request.

```
input_guardrail → [blocked? → END]
      ↓ continue
   profile → memory_retrieval → intent → [route by intent]
      ↓
   calorie? → rag? → food? → meal_plan
      ↓
   output_guardrail → [regenerate? → back to meal_plan, once] → [extract? → memory_extraction] → END
```

| Node | What it does | Why it's a separate step |
|---|---|---|
| **Input Guardrail** | Classifies the incoming message: medical emergency, medication misuse, self-harm, or none. A block returns a fixed, pre-written safety string — never LLM-generated text — before any other node runs. | You don't want to spend a RAG lookup and a generation call on a message you're about to refuse anyway, and you never want the *refusal text itself* to be something an LLM improvised for a self-harm situation. |
| **Profile** | Loads the user's stored profile, chat history, and previously accepted plans from MongoDB. | Single place that assembles "who is this person" so every later node can just read it from state. |
| **Memory Retrieval** | Pulls a handful of long-term memory facts (preferences, goals, medical facts from uploaded documents) and recent events. Pure DB read, no LLM call. | Cheap and always runs — this is what makes the assistant remember "you told me you dislike oats" three weeks later without re-reading the whole chat history every time. |
| **Intent** | A fast LLM call classifies the message into one of six categories (meal plan request, plan modification, calorie question, routine request, nutrition question, general conversation). | Routing. Different intents need genuinely different downstream work — a meal-plan request needs calorie math + RAG + food filtering + generation; "hi, how are you" needs none of that. Doing this classification first avoids wasted work and, more importantly, avoids irrelevant guardrail/RAG noise on unrelated messages. |
| **Calorie** | Runs a pure Python calculator (Mifflin-St Jeor BMR formula + activity multiplier + goal adjustment). No LLM. | This is the clearest example of "the model never does math." An LLM asked to compute a BMR will get it *approximately* right most of the time and *wrong* some of the time, in a way that's hard to catch. A formula is never wrong. |
| **RAG** | Hybrid search over a small corpus of clinical-guideline PDFs (diabetes, PCOS, thyroid, hypertension, general diet, protein). | Grounds the response in actual guideline text instead of the model's unverified training-data recollection of nutrition science, and gives the response citable sources. |
| **Food** | Filters a 133-item food database down to a ~40-item list the model is actually allowed to choose from, based on the user's diet type, allergies, and medical conditions. | This is the *pre-generation* half of allergen safety: the model physically cannot suggest a food that isn't on the list it was shown, because the list itself already excludes anything unsafe for this user. |
| **MealPlan** | For plan-generating intents, **two separate LLM calls with deterministic Python in between**: (1) the model picks foods + gram amounts as JSON, (2) Python computes every calorie/macro number from those grams against the database and rebalances any day that's off-target, (3) a second LLM call writes the warm, personalized message *around* the now-finished plan. | This split is the single most important design decision in the codebase — see the calorie-drift story below for why it exists. |
| **Output Guardrail** | A deterministic scan for allergen mentions in the free-text response, plus an LLM call checking for diagnosis language, fabricated medical claims, and foods outside the allowed list. On failure, the pipeline loops back to MealPlan once with corrective feedback; if it fails again, a fixed safe fallback message is returned instead. | The *post*-generation half of safety — catches anything the pre-generation food filter can't (the filter stops the model from building an unsafe *plan*; this catches an unsafe *sentence* in the prose around it). |
| **Memory Extraction** *(conditional — only runs when the message signals a preference/goal, not every turn)* | A small LLM call extracts a durable fact ("dislikes oats," "goal changed to muscle gain") into long-term storage. | Gated rather than unconditional specifically to control LLM call volume/cost — most messages don't contain anything worth remembering long-term. |

## The six invariants — framed as trust boundaries

These are the rules that hold across every feature in the codebase, and they're a good structure for explaining the system's design philosophy in one breath: **the LLM is trusted to make judgment calls (which foods sound good, how to phrase something warmly), and never trusted to be a source of truth for a fact that matters.**

1. **The LLM never does deterministic math.** Calorie/macro targets come from a pure-Python Mifflin-St Jeor calculator; every number in a meal plan is `database_value × grams ÷ serving_size`, computed in Python, never written by the model.
2. **One JSON file (`food_db.json`) is the single source of truth for food macros.** The model never invents a food's nutrition profile.
3. **Safety constraints are a pre-generation allow-list, not a prompt instruction.** "Don't suggest peanuts" is enforced by peanuts never being in the list the model sees, backed up by a post-generation scan — not by hoping the model honors an instruction.
4. **User data isolation is structural, not conventional.** Every database access goes through a repository object that's constructed with the authenticated user's ID and injects it into every query automatically — there's no code path where a developer could forget to scope a query by user and accidentally leak one user's data to another.
5. **The system extracts and reports facts, it never diagnoses.** Applies to memory extraction, medical-document processing, and the output guardrail's own rubric.
6. **Generation is swappable behind one interface.** No code outside one designated file per vendor ever calls a vendor SDK directly — which is what let the project migrate from Groq to Azure OpenAI, and later add a second "challenger" model, as configuration changes rather than rewrites.

## What runs synchronously vs. in the background

**Short, honest answer if asked "is there a background job system / task queue?": no, and that's a deliberate scope decision, not an oversight.** Everything in this app runs synchronously inside the HTTP request/response cycle:

- **Medical document upload** (PDF/image → OCR → LLM fact-extraction → stored as memory) all happens inside the single upload request, before the response is returned. At the scale this app runs at, that's simpler than standing up a task queue (Celery + Redis, or a serverless queue) and a polling/webhook mechanism for the frontend to find out when processing finished. It's the single place in the codebase where a real background-job system would earn its complexity if this needed to scale to larger documents or higher upload volume — the frontend's document list actually already polls every 3 seconds while a document shows `"processing"`, defensively, even though today's synchronous implementation means that status is fleeting.
- **The output-guardrail regeneration loop** (fail → regenerate once → fall back) is *also* synchronous and sequential, not background — it's literally one more LLM call added to the same request when it fires, which is real added latency, not deferred work.
- **Rate limiting** is a MongoDB-backed fixed-window counter (no Redis in this stack at all — deliberately, to avoid adding infrastructure for a feature that a database counter handles fine at this scale) with a TTL index so old counters self-expire; that expiry is MongoDB's own internal background thread, not application code.
- **The one genuinely asynchronous, fire-and-forget piece** is LangSmith tracing (optional, off by default) — LangChain's callback system ships trace data out without blocking the response.
- **Streaming** (the SSE endpoint) is often mistaken for "background work" but isn't — it's the exact same synchronous pipeline, just with the HTTP response flushed incrementally as each pipeline stage finishes, instead of held until the very end. The backend is still doing the same sequential work either way.

## Performance and latency optimizations

Meal-plan generation is the slowest path (two LLM calls plus a reasoning model's "thinking" overhead), and a real, user-reported latency problem (a 7-day plan taking 70-80 seconds) drove a concrete, three-part optimization pass:

1. **Route cheap classification calls to a cheap model.** Intent classification and the safety guardrails' LLM checks are small yes/no-shaped decisions — they don't need a reasoning model's "thinking" budget. A `FAST_CALL_PROVIDER` setting lets those three specific call sites use a fast, non-reasoning model while the actual plan-generation calls keep using the slower-but-better reasoning model. This is a good example of **not paying for capability you don't need on every call** — the same technique behind things like using a small/fast model as a router in front of a bigger model.
2. **Stop re-sending data the next call doesn't need.** Chat history was being replayed into every prompt, including the *full rendered meal-plan table* from prior turns — a plan turn's stored history now gets trimmed to a one-line marker instead. And the food-selection call (picking foods/grams) was receiving the same conversational chat history as the prose-writing call, even though selecting foods for a *new* plan doesn't need the back-and-forth — it was removed from that call entirely. **Net effect, measured live on a comparable request: ~49s → ~25s.**
3. **Perceived latency, separate from actual latency.** A Server-Sent-Events endpoint streams real per-stage progress ("Understanding your request" → "Building your response" → ...) as the pipeline actually executes each node, instead of a frozen spinner for 70 seconds. This is explicitly **not** token-level streaming of the model's output — the output guardrail needs to see a *complete* response before it can decide to pass or reject it, so there's no safe way to show a user text that might get regenerated or replaced with a fallback a moment later. This distinction (stage-progress vs. token streaming, and *why* token streaming wasn't chosen) is a good thing to be able to explain — it shows the streaming decision was made with the safety architecture in mind, not just "streaming is nice."

Other optimizations baked into the design from earlier, worth mentioning if asked generally about performance:
- **`@lru_cache` on the provider factory** — the LLM client object is built once, not per-request.
- **The food database is loaded once and cached in memory** (`@lru_cache` on the loader), not re-read from disk per request.
- **RAG uses a hosted, integrated-embedding vector index (Pinecone)** rather than a local embedding model — no model-loading cost, and it's what let the app run on a stateless serverless platform (Vercel) at all, since a local vector store (the project originally used ChromaDB) doesn't survive a serverless cold start with no persistent disk.
- **Hybrid search + reranking, not a single dense-vector lookup**, because pure semantic search on a small (~50-document) knowledge base sometimes missed an exact keyword match a plain BM25 keyword search would catch — dense (Pinecone) and sparse (in-process BM25) results are fused with Reciprocal Rank Fusion (`k=60`, the standard constant from the original RRF paper) and then reranked by an LLM call down to the final top-6, pulling a pool of 20 candidates from each method first.

## The safety/guardrail architecture as defense-in-depth

Worth walking through explicitly if asked "how do you make an LLM app safe," since it's a genuinely layered design, not a single check:

1. **Input guardrail** (before any generation): classifies for medical emergency / medication misuse / self-harm. A block returns a hand-written, vetted string — the actual safety-critical text a user sees in a crisis is never something an LLM wrote on the spot.
2. **Pre-generation allow-list** (food filtering): the model is shown a food list that's *already* had anything unsafe for this user removed, based on allergies, diet type, and medical conditions (e.g. only low-glycemic-index foods for a diabetic profile). It's structurally impossible for the model to select a food it was never shown.
3. **Deterministic post-generation scan**: after the model writes its response, a regex-based scan checks whether any of the user's allergens appear in the free text, independent of whether the structured plan itself is safe (this catches, for instance, an allergen mentioned only in the prose, not the plan table).
4. **LLM-based post-generation check**: a second model call reviews the response for diagnosis language, fabricated clinical claims, and — as of a recent fix — adjudicates the deterministic scan's allergen findings with actual reading comprehension (does this sentence *recommend* the allergen, or is it correctly explaining what to avoid?).
5. **One bounded regeneration attempt, then a safe fallback.** If the output guardrail is unhappy, the pipeline loops back and tries once more with corrective feedback; if it's still unhappy, the user gets a generic "I couldn't produce a confident answer" message instead of an unsafe one.

**A good detail to mention if asked about trade-offs**: guardrails in this system **fail open** by default (an internal error → allow the response through) rather than fail closed, because a false positive blocking a legitimate nutrition question was judged worse than an occasional false negative, given there are multiple independent layers underneath. The one deliberate exception is when Azure's own content-filtering system actively confirms a message is unsafe (not "the check errored," but "the vendor's safety system flagged it") — that specific case fails **closed**, because failing open there would mean a real content-filter hit for something like a self-harm message gets silently waved through. Being able to articulate *why* the fail-open default exists, and *why* one specific case deliberately overrides it, is a much better answer than either "everything fails closed" (sounds safe, breaks availability constantly) or "everything fails open" (sounds available, is actually unsafe for the one case that matters most).

**Also worth mentioning**: the allergen scan's design evolved under real pressure. The first version was a strict, unconditional rule — any mention of an allergen word blocked the response, full stop. Live testing found this was actually *too* strict for a common allergen like milk: a response correctly explaining "avoid milk-derived ingredients, here's why" got blocked because the word "milk" appeared in it. The fix wasn't a smarter regex (that was tried first and hit a ceiling), it was changing the *architecture*: the deterministic scan's findings are now a hint fed to the LLM check, which has real reading comprehension and can tell "recommends milk" from "correctly explains to avoid milk" — the scan only becomes the absolute authority if the LLM call itself fails to respond at all. That's a good example of recognizing when a rule-based approach has hit its ceiling and a judgment call genuinely needs judgment, not more rules.

## Data model and isolation

MongoDB Atlas, several collections (users, chat sessions, accepted plans, consent log, access audit log, long-term memory facts, episodic events, medical document metadata, rate-limit counters). The structural guarantee: every authenticated request constructs a small repository object scoped to that specific user's ID, and every query that object makes automatically includes that ID — there's no method on it that takes a bare "give me this document" without also requiring the caller's user ID to match. This means a bug that leaks another user's data would have to be a bug in that one central class, not a bug that could be introduced independently in any of the dozens of places the app reads or writes user data. Consent for storing medical/health data is its own append-only event log (not just a boolean flag) so there's a full history of when it was granted or revoked, and an access-audit log (90-day TTL) records every read of medical data.

## Testing strategy — how do you test a system with a non-deterministic component?

Two distinct layers, because they answer different questions:

1. **Unit tests (421 tests, zero API calls, run in CI on every push).** These cover everything deterministic: the calorie formula, the food filter's allergen/diet exclusion logic, the plan-arithmetic/rebalancing code, the guardrail's regex scans, routing logic, database isolation. Fast, free, and — critically — they can assert an *exact* expected output, because none of it depends on what an LLM decides to say.
2. **An offline evaluation harness with an LLM-as-judge** (run manually, real API cost, not in CI — a golden set of ~19 realistic conversations spanning categories like meal-plan requests, allergy edge cases, medical-context questions, ambiguous/unsafe messages). Each case is scored two ways: **deterministically** (was a plan produced when expected, do the calories in the plan actually match the database, are there any allergen violations) and via **DeepEval metrics** — a second LLM acting as a judge, scoring faithfulness to the retrieved clinical context, answer relevancy, and two custom rubrics for medical-safety and completeness. The judge is deliberately pinned to a fixed model regardless of which model is being evaluated, so that when comparing two candidate models, the judge is a constant, not something that changes between runs.

This two-layer split is a genuinely good answer to "how do you test an LLM app": you can't unit-test "is this response good," but you also shouldn't rely *only* on an LLM judge for everything that's actually checkable — the things that have a factually correct answer (does this plan's math check out, was an allergen ever mentioned) are asserted exactly, in code, and the LLM judge is reserved for the genuinely subjective/semantic parts (does this feel medically appropriate, is it faithful to the source material).

## Infrastructure and scaling considerations

Deployed as two separate Vercel projects (backend, frontend) from the same repo — serverless functions, not a long-running process. That constraint shaped real decisions: the original vector store (ChromaDB, local-disk-backed) had to be replaced with Pinecone (a hosted vector database) specifically because a serverless function's local disk doesn't survive between invocations, so anything stateful has to live in an external service. The roadmap's stated end-state is a move to Azure Container Apps (a long-running container, not serverless functions) — Vercel is explicitly treated as an interim hosting choice, not the final architecture, which is itself a reasonable thing to say out loud if asked "why Vercel" — it was fast to stand up and iterate on, with a known, accepted migration path once the app's requirements outgrow serverless constraints.

## Three ready-to-tell debugging stories

Good material for "tell me about a challenging bug" — each is a real incident from this project, with a clear problem → investigation → fix → lesson shape.

**1. The calorie-drift misdiagnosis.** For a long stretch, a recurring set of eval-harness failures (generated meal plans landing 16-34% under their calorie target) was logged as "stochastic model variance" — LLMs are non-deterministic, so a failure that comes and goes looks like noise. Four separate rounds of prompt tweaking ("be more precise about hitting the target," stronger and stronger wording) each moved the number a little or not at all. The actual breakthrough came from asking a simple question: *which direction* were the failures? Every single one, across every day, on two architecturally different models, was an *undershoot* — never an overshoot. Noise doesn't do that; a genuine constraint does. Digging in found two real root causes: the food list handed to the model was ranked "protein first" within every macro category, so the foods available for breakfast and snacks were almost entirely low-calorie-density protein sources — the target was physically unreachable at sane portion sizes. And separately, the model was writing every calorie figure itself and the code was only summing them — nothing actually recomputed a number from the database. The fix was architectural, not another prompt tweak: the food-selection algorithm now ranks non-protein foods by calorie density (so oats, rice, and oils are actually available), and a new deterministic module computes every single number in the final plan from the database, with the model only ever choosing *which* foods and *roughly how much*. **The lesson worth stating explicitly**: "the model is stochastic" is a hypothesis, not a diagnosis — check whether an error is one-directional and consistent before accepting "noise" as the explanation, because noise predicts scatter in both directions and this didn't scatter.

**2. The guardrail that blocked its own correct answers.** Covered in detail above (the allergen-scan architecture evolution) — worth having as a story because it's a good example of iterating past an initially-reasonable design once live data showed its actual failure rate, and of the "give a rule-based system to a component that can actually reason" fix pattern.

**3. Reasoning models silently returning nothing.** Twice, across two different LLM providers (first Groq, later Azure OpenAI), switching to a newer "reasoning" model class caused chat responses to come back completely empty with no visible error. The root cause both times was the same: reasoning models spend part of their token budget on hidden internal "thinking" before producing the visible answer, and a `max_tokens` limit sized for a non-reasoning model left no room left over for any actual output once the hidden reasoning consumed its share. The fix was setting an explicit, smaller "reasoning effort" parameter and raising the token budget — but the more useful lesson is procedural: **this exact failure mode recurred a third time later** (in an evaluation-harness component) before it was fully internalized as "the first thing to check," which is itself worth mentioning — some bug classes are worth writing down explicitly the first time so the second and third occurrence get diagnosed in minutes instead of being rediscovered from scratch.

## Numbers cheat sheet (things worth having exact, not approximate)

| Fact | Value |
|---|---|
| LangGraph pipeline | 10 nodes, 2 more agents run outside the graph (plan-accept, email) |
| Unit tests | 421 tests, 35 files, 0 live API calls, runs in CI on every push |
| Eval harness golden set | 19 hand-written cases across 8 categories |
| Food database | 139 items (123 whole foods + 16 "treat"/indulgent items, gated behind explicit request) |
| Food list shown to the model | ~40 items, slot-aware (breakfast 25% / snack 20% / lunch+dinner 27.5% each) |
| Macro split (default) | Protein 30% / Carbs 40% / Fat 30% (shifts to 35/30/35 protein/carbs/fat for diabetes/PCOS) |
| BMR formula | Mifflin-St Jeor |
| Activity multipliers | 1.2 (sedentary) → 1.9 (extremely active), 5 levels |
| Goal adjustment | fat loss −300 to −500 kcal, muscle/weight gain +250 to +400 kcal, maintenance ±0 |
| Chat memory window | last 10 messages |
| RAG: fusion pool | 20 candidates each from dense + keyword search |
| RAG: fusion method | Reciprocal Rank Fusion, k=60 (the paper's standard constant) |
| RAG: final context | reranked down to top 6 |
| Output guardrail regeneration cap | 1 retry, then a fixed fallback response |
| Rate limits | registration 5/hour/IP, login 10/15min/IP, chat 20/5min/user |
| JWT token lifetime | 7 days |
| Measured latency improvement | ~49s → ~25s on a comparable request, after the 3-part latency fix |
| Model roles | primary = a reasoning model (full plan generation), a classic non-reasoning model pinned to cheap classification/safety calls only |
| Deployment | 2 Vercel serverless projects (backend + frontend), interim — target is Azure Container Apps |
