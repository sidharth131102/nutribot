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
