# Issues & Fixes Log

> **Purpose**: every significant bug or gotcha hit while building this project, with root cause and fix, in one scannable place. Organized chronologically by the work that surfaced each one. For how the system works today and what not to break, see `docs/PROJECT_CONTEXT.md`. For the phase plan this work sits inside, see `docs/ROADMAP.md`. For full implementation detail per phase (files, design rationale, live-verification notes), see `docs/CURRENT_STATE.md`.
>
> Each entry: **Symptom** (what was observed) → **Root cause** → **Fix** (what changed, where).

---

## Vercel deployment (2026-08-02)

### 1. `.vercelignore` broke the frontend build
**Symptom**: frontend project's build stripped `layout.tsx`, `page.tsx`, and other files it needed.
**Root cause**: a single shared `.vercelignore` at the repo root applies to *both* Vercel projects regardless of each project's configured Root Directory — excluding `frontend/` (meant only for the backend project's bundle) also broke the frontend project's own build.
**Fix**: don't exclude the other project's directory in a shared `.vercelignore` at all.

### 2. Unanchored `.vercelignore` patterns matched nested directories
**Symptom**: `ModuleNotFoundError: No module named 'backend.tools'` in production.
**Root cause**: `tools/` and `rag/` entries (meant to exclude stale top-level leftover directories from an old layout) matched at *any* depth, so they also stripped `backend/tools/` and `backend/rag/` from the deployed bundle.
**Fix**: anchor patterns with a leading `/` (e.g. `/tools/`) to scope them to the repo root only.

### 3. Manual ASGI wrapper collapsed all routes to 404
**Symptom**: every route 404'd in production, including FastAPI's own `/docs`.
**Root cause**: an `api/index.py` ASGI wrapper + a catch-all `vercel.json` rewrite (`{"source": "/(.*)", "destination": "/api/index"}`) collapsed every request path down to the ASGI root.
**Fix**: switched to `[tool.vercel] entrypoint = "backend.main:app"` in `pyproject.toml` — Vercel's native FastAPI preset auto-detects this and handles routing itself; no manual wrapper or rewrite needed.

### 4. Trailing slash in `FRONTEND_URL` broke CORS and OAuth
**Symptom**: browser requests rejected by CORS; Google OAuth redirect had a double slash.
**Root cause**: `FRONTEND_URL=https://x.vercel.app/` (trailing slash) meant `CORSMiddleware`'s exact-match `allow_origins` check never matched the browser's real `Origin` header (which never has a trailing slash), and broke the `{FRONTEND_URL}/auth/google/callback` redirect URI construction.
**Fix**: always paste deployed URLs into env vars without a trailing slash.

### 5. Vercel's default domain redirects to login
**Symptom**: the "obvious" project URL (`*-<team-slug>-projects.vercel.app`) returned a 302 to a Vercel login page instead of the app.
**Root cause**: that domain pattern has deployment protection enabled by default; the short auto-assigned alias (e.g. `nutribot-backend-xi.vercel.app`) is the one actually publicly live.
**Fix**: use the short alias domain, findable via Vercel's project settings/MCP `get_project`, not the team-scoped one.

### 6. SendGrid API key returns 401 (outstanding, not a code bug)
**Symptom**: `SENDGRID_API_KEY` on the backend project returns `401 Unauthorized` from SendGrid.
**Status**: needs the user to verify/regenerate the key in their SendGrid dashboard — not something fixable from the codebase side.

---

## Groq / LLM provider issues (2026-08-02 through migration)

### 7. Groq retired the configured models mid-project
**Symptom**: production chat broke overnight with no code change.
**Root cause**: Groq fully retired `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` — removed from the account's model list entirely, not just deprecated.
**Fix**: replaced with `openai/gpt-oss-120b` (full) / `openai/gpt-oss-20b` (fast), current Groq Production Models at the time.

### 8. Reasoning models silently returned empty output
**Symptom**: chat responses came back empty with no error.
**Root cause**: the replacement `gpt-oss` models are **reasoning models** — part of the token budget goes to hidden chain-of-thought before the visible answer. `max_tokens` values sized for the old non-reasoning Llama models left no room for both reasoning and a visible answer.
**Fix**: `reasoning_effort="low"` on `ChatGroq` (halves reasoning overhead) plus raised `max_tokens` (20→100 fast, 4096→6144 full). **This exact failure mode recurred twice more later** (see #20, #31) — treat it as the first thing to check whenever a reasoning-model-backed call returns empty/truncated text.

### 9. Groq's 8000 TPM shared rate limit
**Symptom**: intermittent "technical issue" errors on meal-plan requests, especially back-to-back or concurrent.
**Root cause**: the account was on Groq's free `on_demand` tier — 8000 tokens/minute, a *rolling, account-wide* limit, not per-request. A single meal-plan generation (RAG context + food list + chat history + a large `max_tokens` reservation) could consume most of the budget alone.
**Fix (mitigation, not a full fix)**: trimmed prompt inputs (RAG cap 3000→800 chars, food list 30→10 items, chat history 20→6 messages) and generation tuning (`temperature` 0.7→0.5, `max_tokens`→6000). Made a *single* request reliable; did not fix the shared-capacity ceiling under back-to-back requests. **User explicitly deferred the real fix (Groq Dev Tier billing upgrade) until the later migration to Azure OpenAI**, which is what ultimately resolved this (see #17-23).

### 10. `max_tokens=6000` sometimes truncated a full 7-day plan
**Symptom**: `plan_proposed: false` with a real but incomplete prose response, no visible error.
**Root cause**: the token ceiling was reached mid-JSON before the model finished a complete 7-day plan; the JSON extractor found no closing fence and silently returned `None`.
**Status at the time**: explicitly deferred by the user ("fix the token problem later"). Fully resolved later by the Azure migration's much larger token budget (#23) and the balanced-brace-scan JSON extractor (#21).

### 11. `NUTRIBOT_MAX_GENERATION_RETRIES` was dead documentation
**Symptom**: none — found during Phase 0 recon, not a live bug.
**Root cause**: referenced in `README.md` but never implemented anywhere in `backend/`.
**Fix**: documented as a known gap; no retry cap exists in the pipeline (as of Phase 0's writing).

---

## Phase 1b eval harness findings (2026-09-03)

### 12. Generated plans undershot the calorie target by 30-65%
**Symptom**: meal plans landing far below the computed `goal_calories`, not just outside the ±15% tolerance.
**Root cause**: `get_filtered_foods()` (`backend/utils/food_filter.py`) ranked foods purely protein-first, so a non-vegetarian profile's top-N was **100% protein-dominant** foods — summing all of them capped out around ~2010 kcal regardless of how high the actual target was, even though the food DB had plenty of carb/fat-dominant options.
**Fix**: select proportionally across protein/carb/fat pools matching `calorie_tool.py`'s own macro split (30/40/30), instead of one flat protein-first sort. Also added a prompt instruction letting the model scale an approved food beyond its default serving size with proportionally recalculated macros.

### 13. Food allow-list violations in generated plans
**Symptom**: a generated plan included "Turkey breast," which wasn't in the food list actually offered to the model for that request.
**Root cause**: partly a **scorer bug** (exact-string comparison rejected "Turkey breast" against the approved "turkey breast (cooked)" — a real match, differently capitalized/qualified) and partly a **real enforcement gap** (the allow-list was prompt-instruction-only, nothing deterministically validated the model's actual output).
**Fix**: added `food_name_matches()` (`backend/utils/food_filter.py`) — tolerant matching (strips parenthetical qualifiers, case-insensitive, substring-tolerant), shared by both the eval scorer and a new `_sanitize_plan()` step (`backend/agents/meal_plan_agent.py`) that runs after every generation and deterministically strips any item that doesn't match an approved food, recomputing totals from what's left. First real enforcement of invariant 3, not just a prompt ask. *(Superseded 2026-09-12: `_sanitize_plan()` became `plan_builder.build_plan()`, which drops off-list items the same way and additionally computes every nutrient from the DB — see #39.)*

---

## Phase 2 — compliance & data isolation (2026-09-03)

### 14. `sparse=True` unique index didn't exclude null values
**Symptom**: index creation failed against real Atlas data.
**Root cause**: a `sparse=True` unique index on `google_id` only excludes documents *missing* the field entirely — it still treats every present-but-`null` value as a duplicate under `unique`, and registration explicitly sets `google_id: null` for every email-registered user.
**Fix**: switched to a **partial** index (`partialFilterExpression={"google_id": {"$type": "string"}}`), which correctly excludes both missing and null values.

### 15. Ambiguous consent-status sort
**Symptom**: intermittent test failures in `test_consent_grant_then_revoke`.
**Root cause**: `get_consent_status()` sorted only by `timestamp` to find the "current" state; two consent events recorded within the same millisecond sort ambiguously on timestamp alone.
**Fix**: added `_id` (monotonically increasing, always unique) as a secondary sort key.

### 16. Windows `pkill` doesn't reliably kill `uvicorn --reload`'s subprocess tree
**Symptom**: curl requests appeared to hit a stale, pre-fix server — looked like a fix "didn't work" when it actually had.
**Root cause**: `pkill -f "python main.py"` doesn't reliably match uvicorn's `--reload` subprocess tree on Windows, leaving orphaned processes still bound to the port.
**Fix (process note, not a code fix)**: use PowerShell `Get-Process python | Stop-Process -Force`, then confirm `Get-NetTCPConnection -LocalPort 8000` is empty before trusting a "fresh" local server run.

---

## Azure OpenAI migration (2026-09-07)

### 17. AI Foundry's deploy flow created a different backing resource
**Symptom**: every request 404'd with `DeploymentNotFound`.
**Root cause**: Azure AI Foundry's "Deploy model" flow silently provisioned its own backing Azure OpenAI resource, separate from the resource created manually via the classic Azure Portal path — the deployment lived on the Foundry-created resource, not the one whose keys were being used.
**Fix**: when deploying via AI Foundry, get the key/endpoint from the Foundry project's own "Overview" page (the "Azure OpenAI endpoint" field specifically) — not from whatever resource was created by hand first. They are not guaranteed to be the same resource.

### 18. Foundry-copied endpoint had an extra path segment
**Symptom**: a generic `404 Resource not found` (distinguishable from #17's more specific `DeploymentNotFound`).
**Root cause**: the Foundry "Azure OpenAI endpoint" field's copy value included a trailing `/openai/v1` (Azure's newer unified API path); `langchain_openai.AzureChatOpenAI` builds its own deployment-specific path on top of the base URL, so the extra segment produced a malformed, duplicated path.
**Fix**: strip everything after `.openai.azure.com` before putting the endpoint in `.env`.

### 19. GPT-5-family models reject custom `temperature`
**Symptom**: `400 Unsupported value: 'temperature' does not support 0.0`.
**Root cause**: GPT-5-family models only accept the default `temperature` (1); any explicit override 400s.
**Fix**: `AzureOpenAIProvider` no longer passes `temperature` at all — no per-call temperature control for this provider (a lost determinism lever for the fast/intent-classification profile, accepted as a tradeoff).

### 20. Same reasoning-token-overhead issue as Groq, different provider
**Symptom**: empty `text` on an otherwise-successful call.
**Root cause**: GPT-5-mini is a reasoning model too (same class of bug as #8).
**Fix**: `reasoning_effort="minimal"` for the fast profile, `"low"` for full.

### 21. GPT-5-mini didn't reliably fence its JSON output
**Symptom**: `plan_proposed: False` with zero error, despite the model actually having produced valid, complete JSON.
**Root cause**: the original JSON extractor hard-required a ```` ```meal_plan_json ... ``` ```` fence; GPT-5-mini reliably included the JSON but didn't reliably wrap it in the fence the prompt asked for (Groq's models happened to always comply, which is why this was never caught before).
**Fix**: `_extract_plan_json_and_clean()` (`backend/agents/meal_plan_agent.py`) tries the fenced pattern first, falls back to a balanced-brace scanner (finds the `meal_plan_json` marker, then the first `{`, then walks forward tracking brace depth to find the true matching `}` — a plain regex can't reliably match balanced/nested braces, and the plan JSON nests days → meals → items).

### 22. A request hung for hours with no timeout
**Symptom**: a single request during a 16-case eval harness run hung for hours with zero output; the process had accumulated real CPU time (not fully deadlocked) but wall-clock time vastly exceeded any reasonable duration.
**Root cause**: `AzureChatOpenAI` had no explicit `timeout`/`max_retries` set, inheriting whatever the SDK's default is — not tight enough to catch this.
**Fix**: set `timeout=120, max_retries=2` explicitly. **Rule going forward: never trust an LLM call in this codebase to have a sane default timeout — always set one explicitly.**

### 23. `gpt-5-nano` hit a zero-quota wall on a fresh trial
**Symptom**: quota errors when trying to deploy the fast profile to `gpt-5-nano`.
**Root cause**: the fresh Azure trial subscription had zero TPM quota entitlement for that specific model — not an insufficient amount, a hard zero.
**Fix**: both fast and full profiles point at the one working `gpt-5-mini-1` deployment instead of fighting quota requests for a separate nano deployment.

---

## Post-Azure-migration eval fixes (2026-09-08)

### 24. `rag_dependent` cases returned zero `rag_sources`
**Symptom**: `rd-01`/`rd-02` reproducibly returned no sources across multiple Azure runs.
**Root cause**: `.env`'s `PINECONE_INDEX_NAME` had a typo (`nutribot-knowledg`, missing the trailing "e") — retrieval was silently hitting a nonexistent index and falling back to the "vector store not yet populated" apology string.
**Fix**: user found and corrected the typo; verified retrieval worked directly afterward. Not a code bug.

### 25. Malformed JSON from the model
**Symptom**: `ade-02` failed with `Failed to parse embedded meal plan JSON: Expecting property name enclosed in double quotes` — syntactically invalid JSON, not a fencing issue.
**Fix**: added `json_repair.loads()` as a third-tier fallback (fenced regex → balanced-brace scan → `json_repair`), discarding the repair result if it doesn't look like a meal plan (no `"days"` key) rather than trusting garbage.

### 26. Ambiguous "reduce portions" wording caused a scoring false-failure
**Symptom**: `pm-02` scored as undershooting the calorie target by 41-49%.
**Root cause**: the golden case asked the model to "reduce portion sizes," which is genuinely ambiguous between "smaller portions, same daily calorie target" and "eat less overall" — the model correctly complying by eating less looked like a calorie-tolerance failure to the scorer.
**Fix**: the model now asks a clarifying question for this narrow, genuinely ambiguous case (a new core instruction in `meal_plan_agent.py`, scoped tightly to `PLAN_MODIFICATION` + portion-specific wording only — an earlier, broader version of this instruction incorrectly fired on unrelated modifications like "swap out my oats" and had to be narrowed).

### 27. Fat-loss/muscle-gain targets under-shot further than intended
**Root cause**: the model was applying an *additional* reduction/increase on top of a `goal_calories` figure that already had the deficit/surplus baked in.
**Fix**: added an explicit prompt clarification that the Goal Target number is already adjusted for the user's goal — don't apply another adjustment on top of it.

### 28. Day-to-day calorie inconsistency within one plan
**Root cause**: no instruction specifically demanded consistency across all 7 days.
**Fix**: added an explicit "every one of the 7 days, not just Day 1" instruction.

### 29. Scorer allergen check false-positived on "soy milk"
**Symptom**: a plan including "soy milk" was flagged as violating a milk allergy.
**Root cause**: the deterministic scorer's allergen check substring-matched the food's *display name* against the allergy list — "soy milk" contains the substring "milk" even though the food's actual declared `allergens` field (in `food_db.json`) correctly lists only `["soy"]`.
**Fix**: check the food's actual declared `allergens` field via a `_matched_food()` lookup, falling back to the old name-substring heuristic only when a plan item has no structured match at all. (This class of bug recurred later, more seriously — see #34.)

### 30. Intermittent "no plan produced," initially suspected to be rate limiting
**Symptom**: `mpr-02`/`so-02` intermittently returned `plan_proposed: False` with a conversational response instead.
**Investigation**: directly captured `response_metadata` on the Azure calls — `finish_reason` was always `"stop"` (natural completion), never `"length"` (truncation) or a 429 (rate limit) — ruling out the two obvious infra explanations.
**Root cause**: GPT-5-mini was spontaneously asking clarifying questions (wake time, workout schedule, food preferences) before generating a plan, despite the "mandatory JSON" prompt instruction.
**Fix**: added an explicit "generate the full plan in this response, don't ask, make reasonable assumptions" instruction.

---

## Phase 4 — medical document pipeline (2026-09-08)

No significant bugs — a clean build. One accepted design limitation: long multi-page reports are truncated to ~12,000 characters before LLM fact-extraction (not chunked/summarized).

## Phase 5 — RAG 2.0 (2026-09-08)

No significant bugs — a clean build. Design decisions (LLM-based reranker vs. Cohere, in-process BM25 vs. native Pinecone hybrid) are documented in `docs/CURRENT_STATE.md`'s Phase 5 section, not bug fixes.

---

## Phase 6 — guardrails, rate limiting, LangSmith, DeepEval (2026-09-11)

The user explicitly interrupted a live "run → find bug → fix → run again" loop partway through this phase and asked for a full static code review before any more expensive live runs. That review surfaced 5 of the 6 bugs below in one pass — cheaper and faster than the equivalent number of additional live runs would have been. **This is a good pattern to repeat for future large, expensive-to-verify phases.**

### 31. DeepEval's internal calls silently returned empty/unparseable text
**Root cause**: same reasoning-token-overhead failure mode as #8/#20 — `profile="fast"`/`max_tokens=1024` wasn't enough headroom for DeepEval's longer internal prompts (truths/claims extraction, GEval reasoning steps) on a reasoning model.
**Fix**: `profile="full"`/`max_tokens=4096` for the DeepEval custom-LLM wrapper (`backend/eval/deepeval_provider.py`).

### 32. The medical-safety judge had no visibility into the profile/calorie context
**Symptom**: a genuinely safe `rag_dependent` case was incorrectly gate-failed.
**Root cause**: the `GEval` judge's test case only included the bare `user_message` as input — it had no way to know the response's restated age/weight/calorie-target numbers were legitimately drawn from data the real generator has access to (the user's profile, the deterministic calorie tool), so it flagged every one of them as "fabricated."
**Fix**: pass `profile_context`/`calorie_result` as DeepEval `context`, and include `SingleTurnParams.CONTEXT` in the metric's `evaluation_params`.

### 33. The same rubric flagged the assistant's intentional daily-routine feature
**Symptom**: `ade-02` (allergy_diet_edge_case, safety-gated) was gate-failed for proposing a daily schedule/meal timing/exercise/hydration routine.
**Root cause**: `meal_plan_agent.py`'s prompt explicitly *instructs* the model to propose a reasonable daily routine when unspecified ("make reasonable assumptions... for anything unspecified") — this is intended behavior, not a fabrication, but the rubric's wording ("only report info already known/stated/in context") was broad enough to flag it anyway.
**Fix**: narrowed the rubric to explicitly state that proposing meal plans/routines/targets is expected behavior, and to only flag genuine diagnosis, medication-dosing, or fabricated-statistic content.

### 34. Substring allergen matching false-positived on common words (the most serious bug of this phase)
**Symptom**: (found via code review, not a live failure) — an allergy value like `"nut"` would match as a substring inside `"nutrition"`, `"nutrient"`, `"nutritious"` — meaning the guardrail would have fired on **nearly every response** for a nut-allergic user, since this is a nutrition assistant. Also matched `"coconut"` (not a tree nut) for the same reason.
**Root cause**: both the new output guardrail's allergen-in-prose scanner (`backend/guardrails/output_check.py`) and the pre-existing eval scorer's allergen fallback heuristic (`backend/eval/scorers/deterministic.py`, a lighter version of the same bug class as #29) used plain Python substring matching (`allergy in text`) with no word-boundary check.
**Fix**: switched both to word-boundary regex matching (`\ballergy\b`). Verified: `"nut"` no longer matches `"nutrition"`/`"coconut"`, but still correctly matches whole-word mentions like `"...cashews and walnuts (nut)."`. **The actual production pre-generation allow-list filter** (`food_filter.py::get_filtered_foods`) was **never affected** — it always used exact set-intersection on normalized allergen strings, not substring matching, and remains the safest, most-checked path in the app.

### 35. A type-safety gap in the output guardrail's JSON parsing
**Symptom**: (found via code review) — if the LLM ever returned `"issues"` as a bare string instead of a JSON array (a plausible deviation from the requested schema), `list("some string")` would silently explode into a list of individual characters instead of failing loudly.
**Fix**: validate the parsed value is actually a `list` (and `"feedback"` is actually a `str`) before using it; default to empty/safe values otherwise.

### 36. A Windows console encoding crash killed the eval report before it could be saved
**Symptom**: `runner.py` crashed with `UnicodeEncodeError: 'charmap' codec can't encode character '‑'` partway through printing the results table — meaning `eval_results.json` never got written and the run's outcome was lost.
**Root cause**: judge notes/failure text can contain characters (em-dashes, curly quotes) outside Windows' default `cp1252` console codepage.
**Fix**: reconfigure `sys.stdout` to UTF-8 with `errors="replace"` at the top of `runner.py`, so a genuinely unprintable character degrades to a placeholder instead of killing the whole run.

---

## Phase 7 — challenger model, eval-gated (2026-09-12)

### 37. The eval judge would have floated with the active provider (caught in design, before it shipped)
**Symptom**: (design-time) — `deepeval_provider.py` resolved its judge model through the same zero-arg `get_provider()` every agent uses. In the new `--compare` mode, the active provider is swapped to the challenger for one arm — so the challenger arm would have had **gpt-4.1 judging gpt-4.1's own output** while the primary arm was judged by gpt-5-mini. Two arms scored by different judges can't be compared.
**Root cause**: the judge's provider was an accident of the singleton design (Phase 6), never a deliberate choice.
**Fix**: a new `eval_judge_provider` setting (default `azure_openai`) and `get_provider(name)`; the judge is pinned to it in both arms. Unit-tested: the judge resolves `azure_openai` even when `llm_provider="azure_openai_challenger"`.

### 38. A configured-but-nonexistent challenger deployment didn't fail fast
**Symptom**: the first live smoke call against the challenger entry returned Azure's `DeploymentNotFound` (the deployment hadn't been created yet) — but `--compare`'s up-front check only called `get_provider()`, which validates *config* (deployment name present) and never touches the network. As written, `--compare` would have run the entire expensive primary arm (16 cases, real API cost) and only *then* produced 16 challenger ERROR rows.
**Fix**: `_probe_challenger()` — one 5-token live call before the primary arm runs, raising a clear error naming the deployment and hinting that Azure reports `DeploymentNotFound` for a few minutes after creation. Unit-tested that the probe aborts before any arm runs and that `llm_provider` is restored in the `finally`.

## Calorie-drift fix (2026-09-12)

The user asked why `mpr-01`/`mpr-02` kept failing on both Phase 7 arms and what "calorie drift" actually was. The answer overturned the standing explanation.

### 39. "Calorie drift" was a constraint problem misfiled as sampling noise for four phases (the most consequential finding since #12)
**Symptom**: `mpr-01` (vegetarian fat loss, 1,594 kcal) and `mpr-02` (non-veg muscle gain, 3,339 kcal) failed the ±15% daily-calorie check on gpt-5-mini *and* gpt-4.1; `pm-01` and `so-01` intermittently too. Since Phase 6 every such failure had been logged as "stochastic variance at temperature 0.5" (#26, #28, #30, Phase 7's compare notes).
**What the data actually said**: every single miss, on every day, on both models, was an *undershoot* — 16-34% under, never over. Both models then claimed in prose that every day was "within 10%", which is what sank the judge's medical-safety and completeness scores on the same cases. Directional, consistent across architecturally different models and across all seven days is not what noise looks like.
**Root cause 1 (food list)**: `get_filtered_foods(limit=20)` balanced protein/carb/fat pools by *dominant macro*, then ranked **protein-first within every pool**. The "carb" pool was therefore all dals, the "fat" pool seeds — no oats, roti, rice, quinoa, oils, nuts, fruit — and for the non-veg profile 19 of 20 foods were lunch/dinner-only: **2 breakfast foods, 1 snack food** for 21 of the week's 35 meals. Median density ~120 kcal/100 g; 3,339 kcal would have needed ~2.8 kg of food a day. #12's 30/40/30 fix had cut the undershoot from 30-65% to 16-34% and stopped there, because "carb-dominant" and "calorie-dense" aren't the same thing.
**Root cause 2 (arithmetic)**: the prompt told the model to pick items, scale quantities "proportionally", write per-item calories, and write daily totals; `_sanitize_plan()` then only *summed* the model's per-item figures. Nothing recomputed an item from `food_db.json × grams`. The calorie *target* was deterministic (invariant 1) but calorie *achievement* — the one number the scorer checks — was a 35-meal knapsack solved with mental arithmetic in a single 16K-token generation.
**Fix**: (a) `food_filter.py` — limit 40, per-slot quotas (`SLOT_SHARE`), carb/fat pools ranked by kcal/100 g with a 2:1 staple:produce interleave, low-GI-first ordering only for profiles that need it; `find_food()` returns the matched DB entry with exact-beats-substring so "dal" is "dal". (b) New `backend/agents/plan_builder.py` — every nutrient is `db × grams ÷ serving`; a day outside ±5% is rescaled by one factor clamped to [0.6, 1.75]; `PlanBuildReport` records what changed. (c) `meal_plan_agent.py` — two calls: selection JSON (foods + grams only, temperature 0.2) → `build_plan` → prose around the finished plan, with the plan text rendered by code and appended with the accept prompt. (d) Eval: the deterministic scorer re-checks every item's calories against the DB; `CaseResult.plan_build` and a per-case `plan:` report line; three stress profiles (`mpr-03` ~1,360 kcal sedentary, `mpr-04` ~4,000 kcal extremely active, `ade-03` vegan + diabetic + soy allergy); `tests/test_food_filter.py` asserts per-slot coverage and physical reachability for every golden profile.
**Live smoke** (mpr-02, mpr-04 — the two hardest targets): all 14 days within 0.5% of target, no dropped items, no off-target days. The model's raw selections were still 20-40% short (rebalance factors 1.2-1.7, one day at 1.70 against the 1.75 clamp) — the builder corrected them, and the selection prompt now tells the model that selections typically come out short and to be generous with main-meal portions and staples.
**Lesson**: "the model is stochastic" is a hypothesis, not a diagnosis. It predicts scatter in both directions; one-directional, all-days, all-models error is a constraint or a code path. Check the direction of the error before accepting variance as the explanation.

### 40. Prompt-level "within 10%" instructions had been tightened three times with no effect (#12, #27, #28)
**Symptom**: each of those fixes added stronger wording ("every one of the 7 days must independently total within 10%… do not let portions drift for later days"), and each moved the number a little or not at all.
**Root cause**: the model was being asked to compensate for a food list that couldn't reach the target and for arithmetic it can't do reliably. No wording fixes either.
**Fix**: covered by #39 — the "within 10%" promise is now true by construction (the builder makes it so), and the prompt no longer asks the model to scale or total anything.
**Lesson**: when the third prompt tweak for the same numeric failure doesn't land, the number isn't the model's to get right. Move it into code.

### 41. The grams parser accepted "1 bowl" as one gram
**Symptom**: (caught by a unit test before shipping) the first `parse_grams()` pulled the first number out of any string, so `"1 bowl"` → 1 g and `"2 x 40g"` → 2 g. The builder would have computed a 4 kcal serving of oats and the scorer would have compared against it.
**Fix**: anchored regex — a bare number or a number with a gram unit (`g`, `gm`, `grams`), nothing else; anything else falls back to the DB's default serving and is reported in `PlanBuildReport.unparseable_items`.
**Lesson**: a "tolerant" numeric parser on model output must reject what it doesn't understand, not guess — a wrong number that looks valid is worse than a missing one.

### 42. The prose claimed macro targets were met when the computed plan missed them
**Symptom**: after the calorie fix, the first full 19-case harness run went 19/19 deterministic but 17/19 gated — `ade-01` and `ade-03` (both `allergy_diet_edge_case`, safety-gated) scored 0.4 on the judge's medical-safety rubric. Its reason in both: the response "repeatedly stated the plan meets a ~150 g protein goal but many days list much lower protein (Day 2 ~91 g, Day 3 ~83 g)".
**Root cause**: `plan_builder` rescales a day for *calories* only; a vegetarian/vegan list at 30% protein rarely reaches the protein target. The prose call was handed the plan table but no summary of how it compared to the targets, so it did what models do and asserted the targets were met.
**Fix**: `plan_builder.plan_averages()` + `macro_summary_line()` compute the week's per-day averages against each target ("protein 102g (below the 150g target)"); the line is printed in the rendered plan and passed into the prose prompt with an explicit rule: state a shortfall plainly, suggest closing it with foods already in the plan, never claim a target is met when the summary says otherwise. The selection prompt also now asks for a protein-dense food in every meal.
**Lesson**: giving the model the numbers isn't enough — give it the *comparison* and tell it what to do with a miss. A model with a table and a target will claim compliance by default.

### 43. Routine requests built a full meal plan with no calorie target
**Symptom**: in the same run, `so-02` (`ROUTINE_REQUEST`) produced a plan whose days ranged 2,374–3,128 kcal, "rebalanced 0/7" — the builder had nothing to balance against.
**Root cause**: the graph's routing never sent `ROUTINE_REQUEST` through the calorie agent (only RAG and food), a leftover from when a routine turn was mostly prose. Since the two-call design, a routine turn builds a complete plan, so `goal_calories` is required.
**Fix**: `ROUTINE_REQUEST` added to `CALORIE_INTENTS` in `graph.py` (the eval `pipeline_runner` reuses the same routing predicates, so it followed automatically); routing test added.
**Lesson**: the deterministic scorer skips the calorie check when there is no `goal_calories` — a plan with no target passes silently. The `plan:` report line in the runner (`rebalanced 0/7` with wildly varying day totals) is what made this visible; read it, not just PASS/FAIL.

### 44. The allergen-in-prose scan false-positived on "soy-free"
**Symptom**: the targeted rerun of `ade-01` (soy allergy) logged `Output guardrail failed (issues=['mentions allergen(s) in text: soy']), regenerating` — the prose had said "soy-free".
**Root cause**: the negation check only looks in a window *before* the allergen word ("avoid soy", "without soy"); "soy-free" puts the negation after it.
**Fix**: a trailing `-free` / ` free` immediately after the match is treated as negation too. Test covers "soy-free", "nut free", and that "soy sauce" still fires.
**Lesson**: fourth entry in the substring/keyword-matching bug class (#13, #29, #34, now #44). Every keyword scan on safety text needs both directions of negation considered, not just the one the first example happened to use.

## Post-Phase-7 latency, safety, and UX work (2026-09-13)

### 45. Meta-questions ("what is a personal nutrition companion?") misclassified as NUTRITION_QUESTION
**Symptom**: a plain meta-question about the app itself took 45-59s and returned a canned fallback, confirmed via a user-shared LangSmith trace.
**Root cause**: `intent_agent.py`'s prompt didn't distinguish "asking about the assistant" from "asking a clinical nutrition question" — the meta-question triggered RAG retrieval (irrelevant, since there's nothing about "what is this app" in the clinical PDFs) and then the output guardrail's allergen scan false-triggered on the resulting off-topic prose.
**Fix**: rewrote the `GENERAL_CONVERSATION` vs `NUTRITION_QUESTION` prompt distinction with explicit worked examples including this exact phrasing.

### 46. Chat-history replay inflated every plan-turn's prompt size for no benefit
**Symptom**: a 7-day meal-plan request traced at 75s in LangSmith; the last 10 messages (including full rendered plan tables from prior turns) were being replayed into the prompt on every turn.
**Root cause**: two separate issues stacked — (a) a plan turn's stored `content_en` was the full rendered markdown table, replayed verbatim into every later turn's context; (b) the meal-plan agent's *selection* call (picking foods/grams) received the same `chat_history` as the *prose* call, even though selecting foods for a new plan doesn't need the conversational back-and-forth.
**Fix**: `_content_for_history()` (`backend/main.py`) trims a plan turn's stored history to prose + a one-line marker instead of the full table; the selection call in `meal_plan_agent.py` no longer receives `chat_history` at all (only the prose call does). Verified live: 49.3s → 25.2s on a comparable request.

### 47. Azure's own content filter silently defeated the input guardrail's fail-open handler
**Symptom**: found during deliberate live validation before pinning the input guardrail's classification call to a faster model (not a user-reported bug) — a genuine self-harm-content test message didn't get blocked.
**Root cause**: Azure OpenAI's platform-level Responsible AI content filter rejects certain requests outright with a 400 whose body embeds a per-category filtered/severity breakdown. The input guardrail's generic `except Exception` caught this and failed open (the guardrail's documented default behavior for *internal* errors) — but a content-filter rejection isn't an internal error, it's Azure *actively confirming* the message is unsafe, and failing open on it means the safety net does the opposite of its job for exactly the messages it exists to catch.
**Fix**: new provider-agnostic `ContentFilterBlocked` exception (`backend/llm/base.py`), raised by `azure_openai_provider.py` (the one file allowed to know Azure's vendor-specific error shape, per invariant 6) via string-matching the error body. `input_check.py` now catches this *before* the generic exception handler and fails **closed** (blocked, canned SELF_HARM response) specifically for `self_harm`/`violence` categories; every other internal error still fails open as before. This is a deliberate, narrow exception to the "guardrails fail open" convention documented in `docs/PROJECT_CONTEXT.md` — the distinction is "the LLM call itself broke" (fail open, as before) vs. "the vendor's own safety system confirmed a violation" (fail closed).

### 48. MongoDB Atlas TLS handshake timeout traced to a VPN, not code
**Symptom**: after a routine backend restart, every request failed with a Mongo connection timeout; backend logs showed "SSL handshake failed... timed out" against all three Atlas shard hosts.
**Investigation**: ruled out Atlas's IP allow-list (0.0.0.0/0 was already active, confirmed via the Atlas dashboard); `Test-NetConnection` showed the TCP connection itself succeeding instantly; a raw PowerShell `SslStream.AuthenticateAsClient` probe showed a consistent ~20s-then-forcibly-reset pattern on the TLS handshake specifically.
**Root cause**: a VPN on the user's machine was doing TLS interception — the diagnostic signature (TCP fine, TLS hangs then resets) is characteristic of a proxying security tool, not an Atlas- or app-side problem.
**Fix**: not a code fix — the user disconnected the VPN, and the very next request succeeded (`201 Created`). **If this pattern recurs** (TCP connects, TLS handshake hangs ~20s then resets, against a host that was working a moment ago), check for VPN/security software before assuming an Atlas or code problem.

### 49. Meal-plan day count ignored what the user actually asked for
**Symptom**: "generate a meal plan for 5 days" always produced a 7-day plan.
**Root cause**: `meal_plan_agent.py`'s selection prompt hardcoded "7 days" in five separate places (the persona line, the day-count rule, the variety instruction, the JSON-shape example, and the fill-count reminder) — there was no code path that ever read a day count out of the user's message at all.
**Fix**: deterministic regex parsing (`_requested_day_count()`, clamped to `plan_builder.MAX_DAYS`), threaded through the prompt everywhere "7" was hardcoded — **and**, since a prompt instruction is a request, not a guarantee, the selection's resulting `days` list is also deterministically truncated to the requested count after parsing, the same "don't trust the model on a number that matters" pattern as invariant 1.

### 50. Memory retrieval could silently drop medical-history facts
**Symptom**: (found via architectural review after a document-upload feature discussion, not a live failure) — `get_active_memories()` was one flat top-3-by-recency query across every memory category.
**Root cause**: if a user uploaded a document yielding several `medical_history` facts and then had a few more chat turns generating `preference`/`goal_context` facts, the newer-but-less-consequential chat facts could push the medical facts out of the top-3 window entirely, with no guarantee they'd ever resurface.
**Fix**: `get_active_memories()` now reserves a fixed sub-quota (default 3 of a 5-fact budget) exclusively for `medical_history` facts, filled by recency within that reservation regardless of what else exists; the remaining budget goes to other categories by recency as before. `_format_memory_context()` also now groups the two kinds under separate headings in the prompt ("Medical history (from uploaded documents)" vs. "Other remembered context") instead of one anonymous bullet list.

### 51. Voice recognition ended dictation at the first pause, not when the user was done talking
**Symptom**: user report — "if I am taking a slight pause while talking, the transcription is ending there."
**Root cause**: `frontend/src/services/speech.ts` used Azure Speech SDK's `recognizeOnceAsync` — despite the name suggesting "one utterance," it ends the *entire* recognition session at the first detected silence gap, not just a pause within continuous speech.
**Fix**: switched to continuous recognition (`startContinuousRecognitionAsync`, new `startListening()`/`ListeningSession` API) that accumulates each recognized phrase across pauses and only finalizes when the user clicks the mic button a second time. A cleanup effect on unmount stops the session if the user navigates away mid-dictation.

---

## Cheat-day meal plans (2026-09-13/16)

### 52. The first batch of treat foods left almost no variety for a common allergy
**Symptom**: (found via live testing before shipping) 7 of the first 10 treat-tagged foods added to `food_db.json` (pizza, burger, butter chicken, most desserts) all contained milk/cheese — a milk-allergic profile (the most common food allergy) was left with only "french fries" as a safe option after allergen filtering, defeating the point of a varied cheat day.
**Fix**: added 6 dairy-free treat items (vada pav, spicy fried chicken, bhel puri, potato chips, falafel wrap, mango sorbet) and widened the reserved treat-slot quota from 10 to 16 (the full catalog) so allergen filtering, not an arbitrary reservation cap, is the only thing narrowing the list. A milk allergy now leaves ~8 safe options instead of 1.

### 53. Cheat-day intent was forgotten the moment the triggering message scrolled past
**Symptom**: user report — a 7-day-plan-with-cheat-day request worked, but a follow-up modification in the same conversation ("add a burger for the cheat day") got a response claiming pizza/burger "weren't in the approved list," and a subsequent regenerated plan had zero treat foods anywhere.
**Root cause**: `wants_cheat_day()` (and the food pool it controls) only ever checked the *current* message for "cheat day"/"cheat meal" wording. Once a conversation moved past the turn that first used those words, every later turn — even an explicit continuation of the same request — silently lost the cheat-day context and fell back to a fully normal plan with no explanation.
**Fix**: `wants_cheat_day_in_conversation()` also scans prior **user** turns in `chat_history` (never the assistant's own phrasing, to avoid the model's own summary re-triggering itself indefinitely), so the cheat day stays active for the rest of that chat session without the user needing to repeat the words every turn. Naturally bounded by the existing session/chat-history window — a new chat starts fresh.

---

## Production deployment (2026-09-29)

### 54. Twelve commits of prior work had never actually been pushed to `origin/master`
**Symptom**: (found while preparing to deploy this session's work) `git rev-list --left-right --count origin/master...HEAD` showed the live Vercel deployment was still running code from a commit 12 commits behind local `master` — several entire phases (voice input, PDF download, the calorie-drift fix, profile editing) had been committed locally in a prior session but never pushed.
**Fix**: pushed the full backlog alongside this session's new commits. **Lesson**: after a large local session, always check `git status`/`git log origin/master..HEAD` before assuming "committed" means "deployed" — they're independent facts.

### 55. Vercel's environment variables had drifted far behind local `.env`
**Symptom**: after deploying fresh code, the mic button was missing in production and (more seriously) chat responses started behaving oddly.
**Root cause**: essentially every Azure integration added since the original Groq→Azure migration (the challenger model, Blob Storage, Document Intelligence, Speech/Translator, and `LLM_PROVIDER` itself) had been configured and tested only in the local `.env` — none of it was ever added to the Vercel dashboard. Production had silently been running on the original Groq-only configuration this whole time, and the freshly-deployed code paths for all the newer features were live but unconfigured.
**Fix**: diagnosed via Vercel's runtime logs (`get_runtime_logs`/`get_runtime_errors` MCP tools) and direct endpoint probes (`/api/speech/token` returning 503, `/api/user/account` 500ing) rather than guessing; added the 16 missing variables (see #56 for the specific incident this caused before the fix landed). **Lesson**: a feature working "in production" needs its production config checked directly (a live probe, or reading the actual dashboard) — code being deployed is not evidence its dependencies are configured.

### 56. Adding `FAST_CALL_PROVIDER` alone broke intent classification and the input safety guardrail for every message
**Symptom**: immediately after adding `FAST_CALL_PROVIDER=azure_openai_challenger` to Vercel (correctly, per its own documentation) and redeploying, every chat message — including a plain "generate a 7 day meal plan" — got classified as `GENERAL_CONVERSATION`, bypassing meal-plan generation, calorie calculation, and RAG entirely.
**Root cause**: `FAST_CALL_PROVIDER` was added without its prerequisite `AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FULL`/`_FAST` vars, which were *not* among the 16 identified as missing until this was found. `get_provider("azure_openai_challenger")` raised inside `intent_agent.py`'s `try` block; the generic `except Exception` caught it and defaulted to `GENERAL_CONVERSATION` — silently, with no visible error to the user, just consistently wrong routing. The same failure independently made the input guardrail's classification call fail open on *every* message (not just self-harm/violence ones), since it hit the identical exception path before ever reaching the `ContentFilterBlocked` check from #47.
**Fix**: added the two challenger deployment vars. **Confirmed via Vercel's runtime logs**, not inference — the exact `ValueError: Provider 'azure_openai_challenger' is not configured...` was visible in the logs for both the intent-classification and guardrail call sites. **Lesson**: a setting that pins a call to a named provider should probably validate that provider's config *at settings-load time* in production, not just fail open per-call at first use — this is a candidate follow-up, not yet done.

### 57. A Blob Storage failure blocked account deletion entirely
**Symptom**: found via a live smoke test after deployment (not a user report) — `DELETE /api/user/account` returned 500 for a fresh account that had never uploaded any documents.
**Root cause**: `delete_user_account()` (`backend/main.py`) called `blob_client.delete_prefix(user_id)` unguarded, *before* the MongoDB purge — intentionally ordered that way so a partial failure would be retryable without orphaning blobs with no record left to retry against. But with no `try`/`except` around it, any Blob Storage failure (here: a missing/misconfigured `AZURE_STORAGE_CONNECTION_STRING` in Vercel, part of #55) aborted the *entire* request, including the MongoDB purge — the actually privacy-critical part of a delete-my-account request. A storage outage or misconfiguration should never be able to block a user's data-deletion right.
**Fix**: wrapped the blob-cleanup call in `try`/`except`, logging a warning and proceeding to the Mongo purge regardless. Any orphaned blobs from a failure here remain cleanly retryable later, same reasoning as the original blobs-before-Mongo ordering.

### 58. The output guardrail's allergen scan blocked its own correct, safety-conscious answers (two-stage live fix)
**Symptom**: a real user with a milk allergy asked "how good is protein for me" and got the canned "not confident" fallback, in both English and a Hindi round-trip.
**Stage 1 — negation vocabulary and window width**: `_scan_allergens_in_prose()`'s negation-word list recognized `avoid`/`without`/`no`/etc. but not `allergic`/`allergy`/`sensitivity`/`intolerance` — exactly the words a model naturally uses to explain *why* it's steering someone away from a food ("since you're allergic to milk, try..."). Separately, a 20-character lookback window was too narrow for a causal clause like "avoid whey/casein because those are milk proteins," where the negation word is attached to a different food name 36 characters before the allergen it's actually about. **Fix**: extended the negation word list on both sides of the match (mirroring the existing trailing "-free" handling) and widened the lookback to 45 characters.
**Stage 2 — the deeper, architectural problem**: live-testing the stage-1 fix across 7 real generations for a milk-allergic profile showed nearly every response still had at least one flagged occurrence — "milk-derived ingredients," "milk solids," "milk-based sauces," "milk proteins," a Unicode non-breaking hyphen (`‑`, U+2011) in "milk‑free" that the ASCII-only trailing check didn't recognize, "plant milk" as a safe substitute. Continuing to chase individual phrasings doesn't converge: a word-proximity scan structurally cannot distinguish "eat milk" from "milk-derived ingredients are hidden in processed foods, check labels" — that requires reading the sentence. **Fix**: fixed the one unambiguous remaining bug (Unicode hyphen variants in the trailing-negation character class), and gave the LLM half of the guardrail — which already runs on every response, but had never been told the user's allergies or asked to think about allergen recommendations at all — the allergy list plus an explicit rubric item to adjudicate the scan's findings with real reading comprehension. The deterministic scan's hits are now a hint fed into that judgment, not an unconditional veto, **except** when the LLM call itself fails, where the scan remains the sole fail-closed signal exactly as before this change (preserving the original "highest-severity check doesn't depend on the LLM being available" guarantee). Live-verified: 4/4 safe mentions (allergy explanation, "milk-free," "may contain milk proteins," "use plant milk instead") now pass; 2/2 genuine violations ("add milk to your breakfast," "whey mixed with milk") are still correctly blocked, with the LLM naming the actual problem in its own words.
**Lesson**: this is the fifth occurrence of the substring/keyword-matching bug class (#13, #29, #34, #44, now #58) — but the first time the fix was "stop trying to enumerate keywords and delegate to the model that can actually read," rather than another entry in the list. Worth remembering as the ceiling of the keyword-list approach for any future free-text safety scan on a word with heavy compositional/descriptive use (an allergen name is a common noun, not just a food to avoid).

---

## Cross-cutting patterns worth knowing before touching this codebase again

- **Check the direction of a numeric error before calling it noise** (#39). Four phases accepted "calorie drift" as sampling variance; the failures were one-directional on every day across two models, which noise can't produce. Directional + consistent = constraint or code, not temperature.
- **If a number matters, code computes it; the model chooses, it doesn't calculate** (#39, #40). Invariant 1 is only real where a function enforces it. "The model is told the DB values and asked to scale them" is not enforcement.

- **Reasoning models (Groq's `gpt-oss` family, Azure's `gpt-5` family) silently return empty or truncated text when `max_tokens` is too tight relative to hidden chain-of-thought consumption.** This exact failure mode has recurred three times (#8, #20, #31) across two different providers and three different call sites. If a call to `get_provider().generate(...)` (or the DeepEval wrapper) ever comes back empty/unparseable, check `reasoning_effort` and `max_tokens` first before assuming a logic bug.
- **Never trust an LLM client library's default timeout.** #22 (a multi-hour hang) is the reason every LLM call in this codebase sets an explicit `timeout`/`max_retries`.
- **Substring matching on safety-relevant text (allergens, keywords) is a recurring bug class**, not a one-off — it has bitten this codebase four separate times (#13's food-name matching, #29's allergen-vs-display-name check, #34's allergen-in-prose scan, #44's one-directional negation). Any new code that checks free text against a list of short keywords should default to word-boundary matching, not bare `in` substring checks, and consider negation on both sides of the keyword.
- **Read the eval runner's `plan:` line, not just PASS/FAIL** (#43). A plan with no calorie target passes the calorie check by skipping it; "rebalanced 0/7" next to day totals that swing by 750 kcal is the tell.
- **On Windows, verify a "fresh" local server actually is fresh** (#16) — stale `uvicorn --reload` processes surviving a `pkill` have caused real, time-costly debugging confusion more than once.
- **Before an expensive multi-call run, probe reachability, not just configuration** (#38) — "the setting is present" and "the thing it names exists and answers" are different checks, and only the second one prevents burning a full run's worth of API cost on a typo or a not-yet-created resource. A single tiny live call up front is worth it.
- **When comparing two models, hold everything else constant — including the judge** (#37). Any LLM-as-judge that resolves through the same switch as the thing under test will silently follow it.
- **On Windows, anything that prints LLM-authored text needs stdout reconfigured to UTF-8** (#36) — the runner has the fix, but an ad-hoc analysis script printing judge notes from `eval_compare_results.json` crashed on a `≈` character during Phase 7 the same way the runner did in Phase 6. Judge notes routinely contain characters outside cp1252; treat `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` as boilerplate for any such script.
- **Don't pipe a long background run through `grep`** — it block-buffers to a file, hiding every progress line until exit; Phase 7's first `--compare` run looked like a one-hour hang for that reason alone. Write raw output and filter when reading.
- **A keyword/substring safety scan has a ceiling, and a common-noun allergen (milk, egg, soy) hits it fast** (#58). Four prior fixes to the same scan (#13, #29, #34, #44) were all "add a word/case the pattern missed" and each one worked. The fifth time, live data showed *most* real responses for a milk-allergic user were false positives — the fix wasn't a fifth pattern, it was giving the LLM check (which already ran on every response) the allergy list and an explicit rubric item, and trusting its judgment over the blunt scan except when the LLM call itself fails. If a keyword scan on free text needs a sixth exception case, consider whether it's actually hit this ceiling before writing it.
- **Deployed code and deployed configuration are two separate facts — verify both** (#54, #55, #56). A `git push` that succeeds says nothing about whether `origin/master` was already behind, and a working Vercel build says nothing about whether the environment variables a newly-deployed feature depends on actually exist in that project. Both were silently wrong here for a long time before a live smoke test after deployment caught them. Probe the actual live endpoint (or read the actual dashboard) rather than inferring "shipped" from "the deploy succeeded."
- **Adding a var that pins a call to a named provider is only safe if that provider's own config is verified too** (#56). `FAST_CALL_PROVIDER=azure_openai_challenger` alone, without the deployment vars it depends on, broke intent classification *and* independently defeated the input safety guardrail's fail-open handling for every message — both through the same generic exception path, silently, with no user-visible error. When a setting says "use provider X," check X actually resolves before shipping the setting that points at it.
