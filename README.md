# NutriBot

**NutriBot** is a production-grade AI nutrition assistant that combines a 10-node LangGraph pipeline (with runtime input/output safety guardrails) with a typed memory system, deterministic calorie calculations, RAG-powered nutrition knowledge, and a personalized food database to generate safe, medically-aware meal plans via a conversational interface.

> **Picking up this project for the first time (including as another coding agent)?** Start with `docs/PROJECT_CONTEXT.md` (architecture, conventions, and what you must not break), then `docs/ROADMAP.md` (the phase-by-phase plan and current status), `docs/CURRENT_STATE.md` (detailed build log — what shipped, file-by-file, per phase), and `docs/ISSUES_AND_FIXES.md` (every significant bug hit so far and how it was fixed).

---

## Features

- **Multi-agent LangGraph pipeline** — 10 specialized nodes (Input Guardrail, Profile, Memory Retrieval, Intent, Calorie, RAG, Food, MealPlan, Output Guardrail, Memory Extraction) orchestrated in a stateful graph with conditional routing
- **Runtime safety guardrails** — every message is checked before generation (medical emergency / medication misuse / self-harm) and every response is checked after (diagnosis-language, unsupported claims, allergens in free text), with one automatic regeneration attempt before falling back to a fixed safe response
- **Rate limiting** — Mongo-backed, applied to registration, login, and chat endpoints
- **Observability** — structured JSON logging with a per-request trace_id, plus opt-in LangSmith tracing
- **Typed memory system** — profile (latest-valid fields), short-term (rolling chat window), long-term semantic (extracted preferences/goals with supersession), and episodic (goal changes, accepted plans) layers, assembled by a Context Builder into one typed object per generation call
- **Deterministic nutrition math** — BMR and TDEE are always computed via the Mifflin-St Jeor formula; the LLM never invents calorie numbers
- **Condition-aware macro splits** — automatic carb-to-protein rebalancing for users with diabetes or PCOS
- **Hybrid RAG with reranking** — Pinecone dense search (integrated embeddings, `llama-text-embed-v2`) fused with an in-process BM25 keyword search via Reciprocal Rank Fusion, then reranked by the LLM down to the final top-k; seeded from medical PDF documents (diabetes, PCOS, thyroid, hypertension, etc.)
- **Curated food database** — `data/food_db.json` is the single source of truth for macro values; foods carry allergen, medical, glycemic, region, and diet-type metadata
- **Context-Augmented Generation (CAG)** — every LLM prompt is pre-loaded with the user's profile, calorie targets, RAG chunks, and an approved food list so the model cannot hallucinate out-of-scope items
- **Intent classification** — lightweight fast model routes each message to the correct pipeline branch before any heavy generation occurs
- **Email delivery** — accepted meal plans can be sent to the user via SendGrid
- **Auth** — JWT bearer tokens with email/password registration and Google OAuth 2.0 sign-in
- **Chat history & plan memory** — conversations and accepted plans are persisted in MongoDB and injected into subsequent turns
- **Voice input (speech-to-text)** — a mic button transcribes speech in the browser via the Azure Speech SDK (short-lived token from the backend; the key never leaves the server), auto-detecting between the languages the user lists on their profile. No text-to-speech, by design
- **Multilingual chat** — type or speak in any language; the message is translated to English at the edge, the whole pipeline (guardrails included) runs in English, and the reply is translated back. Decided per message, so switching languages mid-conversation just works. Meal-plan tables keep their food names untranslated
- **Next.js frontend** — chat interface with macro charts, meal plan cards, an accept/modify panel, and a profile editor (including renaming the assistant)

---

## Architecture

```
input_guardrail → [blocked? END] → profile → memory_retrieval → intent
  → [route] → calorie? → rag? → food? → meal_plan → output_guardrail
  → [regenerate? meal_plan] → [extract?] → END
```

### Agent pipeline

| # | Agent | Responsibility |
|---|-------|---------------|
| 1 | **Input Guardrail** | Classifies the message (medical emergency / medication misuse / self-harm / none) before any other work; a block shows a fixed, vetted safety string — never LLM-authored text. Fails open on any error. |
| 2 | **Profile** | Loads user profile from MongoDB, builds the CAG context block, fetches chat history and previous accepted plans |
| 3 | **Memory Retrieval** | Fetches the user's top active long-term memory facts + recent episodic events (pure DB read, no LLM call) |
| 4 | **Intent** | Classifies the message into one of six intents using a fast LLM |
| 5 | **Calorie** | Runs the Mifflin-St Jeor calculator tool; never delegated to the LLM |
| 6 | **RAG** | Hybrid search (Pinecone dense + in-process BM25, fused via RRF) with optional condition-metadata filtering, LLM-reranked down to the final top-k |
| 7 | **Food** | Filters `food_db.json` by diet type, allergens, medical tags, and goal, then selects a slot-aware, macro-balanced 40-item `allowed_foods` list (enough breakfast/snack/main-meal options to reach the calorie target) |
| 8 | **MealPlan** | For plan intents, two LLM calls around deterministic code: (1) the model selects foods and gram amounts as JSON, (2) `plan_builder.py` computes every nutrient from `food_db.json`, rescales any day that misses the target, and renders the plan text, (3) the model writes the personalised message around the finished plan. Non-plan intents are a single conversational call. |
| 9 | **Output Guardrail** | Deterministic allergen-in-prose scan + an LLM check for diagnosis-language/fabricated claims/off-allow-list foods. On failure, regenerates once with corrective feedback; falls back to a fixed safe response if still unsafe. |
| 10 | **Memory Extraction** *(conditional)* | Only runs when the message carries a preference/goal signal or the intent is `PLAN_MODIFICATION` — extracts a durable fact via a small LLM call and stores it with supersession logic. Gated rather than run every turn, to avoid a 3rd LLM call per message. Always skipped when a guardrail blocked/fell back. |

### Intent routing

| Intent | Calorie | RAG | Food |
|--------|---------|-----|------|
| `MEAL_PLAN_REQUEST` | ✅ | ✅ | ✅ |
| `PLAN_MODIFICATION` | ✅ | ✅ | ✅ |
| `CALORIE_CALCULATION` | ✅ | ✗ | ✗ |
| `ROUTINE_REQUEST` | ✅ | ✅ | ✅ |
| `NUTRITION_QUESTION` | ✗ | ✅ | ✗ |
| `GENERAL_CONVERSATION` | ✗ | ✗ | ✗ |

### Directory layout

```
nutribot/
├── backend/
│   ├── agents/          # LangGraph nodes (profile, intent, calorie, rag, food, meal_plan, memory, email)
│   ├── auth/            # JWT handler + Google OAuth 2.0
│   ├── db/              # Motor (async MongoDB) + Pinecone vector store
│   ├── models/          # Pydantic schemas (user, chat, plan)
│   ├── rag/             # PDF ingestion pipeline + Pinecone retriever
│   ├── tools/           # Calorie calculator tool + email tool
│   ├── utils/           # Food DB filter
│   ├── config.py        # Pydantic-settings configuration
│   └── main.py          # FastAPI app entry point
├── frontend/
│   └── src/
│       ├── components/  # ChatBubble, MealPlanCard, AcceptModifyPanel
│       └── services/    # API client (api.ts)
├── data/
│   └── food_db.json     # Macro + safety metadata for all foods
├── main.py              # Uvicorn entry point
├── pyproject.toml
└── requirements.txt
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI 0.115+ |
| Agent orchestration | LangGraph 0.2+ / LangChain 0.3+ |
| LLM | Azure OpenAI — `gpt-5-mini`, behind a provider abstraction (`backend/llm/`); Groq kept configured as a fallback option (`LLM_PROVIDER=groq`) |
| Embeddings | Pinecone integrated inference — `llama-text-embed-v2` (hosted, no local model) |
| Vector store | Pinecone (serverless index, integrated embedding) |
| Database | MongoDB (async via Motor) |
| Auth | JWT (`python-jose`) + Google OAuth 2.0 |
| Email | SendGrid |
| PDF parsing | pdfplumber (+ pypdf fallback) |
| Frontend | Next.js (App Router) + Tailwind CSS |
| Python version | 3.12+ |

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 18+
- A running MongoDB instance (local or Atlas)
- An LLM provider: Azure OpenAI (recommended — much higher rate limits than Groq's free tier; deploy a model in Azure AI Foundry and set `LLM_PROVIDER=azure_openai`) or a Groq API key (free tier at [console.groq.com](https://console.groq.com), `LLM_PROVIDER=groq`)

### 1. Clone & install backend

```bash
git clone <repo-url>
cd nutribot
pip install -e ".[dev]"
```

Or with `uv`:

```bash
uv sync
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
# LLM
GROQ_API_KEY=gsk_...

# MongoDB
MONGODB_URI=mongodb+srv://<user>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB_NAME=nutribot

# JWT
JWT_SECRET=replace-with-a-strong-random-secret
JWT_EXPIRE_MINUTES=10080

# Google OAuth 2.0 (optional)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Email (SendGrid, optional)
SENDGRID_API_KEY=SG.xxx
EMAIL_FROM=noreply@nutribot.ai
EMAIL_FROM_NAME=NutriBot

# Pinecone
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=nutribot-knowledge

# Frontend
FRONTEND_URL=http://localhost:3000
```

Pinecone setup: create a **Serverless index** named `nutribot-knowledge` with integrated embedding model `llama-text-embed-v2` and field map `text → chunk_text` before running ingestion.

### 3. Ingest nutrition PDFs (optional but recommended)

Place PDF files in `data/`. Supported document names:

```
diabetes_guidelines.pdf
pcos_nutrition.pdf
thyroid_diet.pdf
hypertension_diet.pdf
indian_diet_guidelines.pdf
protein_requirements.pdf
```

Then run the ingestion script:

```bash
python -m backend.rag.ingest
```

This parses each PDF, chunks the text (500-token chunks, 50-token overlap), upserts into Pinecone (embedding happens server-side via the index's integrated model, no separate embedding API key required), and writes `data/rag_corpus.json` — a local copy of every chunk used for in-process BM25 keyword search (hybrid retrieval). **Always re-run this full script when adding a new PDF** — Pinecone and `rag_corpus.json` are built together and must stay in sync; don't add a PDF to `data/` without ingesting it. If no PDFs are ingested, RAG-dependent responses will say clinical guidelines are unavailable rather than falling back to any built-in corpus (none currently exists).

### 4. Start the backend

```bash
python main.py
```

The API will be available at `http://localhost:8000`. Interactive docs are at `http://localhost:8000/docs`.

### 5. Start the frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

The UI will be available at `http://localhost:3000`.

---

## API Reference

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health/ping` | Liveness check |

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/register` | Register with email + password |
| `POST` | `/api/auth/login` | Login, returns JWT |
| `GET` | `/api/auth/google-callback` | Google OAuth 2.0 callback (exchanges code for JWT) |

### User Profile

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/profile/me` | Get current user profile |
| `POST` | `/api/profile/create` | Create profile — requires `medical_data_processing` consent first if `medical_conditions` is non-empty (see Consent below). Includes `bot_name` and `spoken_languages` (BCP-47 locales the mic listens for, max 4, one per language) |
| `PUT` | `/api/profile/update` | Update any subset of profile fields (the frontend's profile editor uses this) — same consent gate as above |

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat/message` | Send a message; returns agent response and optional proposed plan. Optional `language` (BCP-47 locale from speech recognition) pins the source language; typed text is auto-detected. The response carries `language` (the reply's language) and `message_english` (what the pipeline processed, when translated) |
| `GET` | `/api/chat/history` | Fetch session message history (`content` is what the user saw, in their language) |
| `GET` | `/api/chat/sessions` | List all sessions for the user |

### Speech

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/speech/token` | Short-lived (10 min) Azure Speech authorization token for browser-side recognition, plus the caller's candidate locales (their `spoken_languages`, or the server default). `503` when voice isn't configured |
| `GET` | `/api/speech/languages` | The locales a user may pick for `spoken_languages`, the server default, and the max selectable |

### Plans

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/plans/accept` | Accept and persist a proposed meal plan; also triggers the SendGrid email |
| `GET` | `/api/plans/saved` | List previously accepted plans |

### Consent

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/consent/grant` | Grant `medical_data_processing` consent |
| `POST` | `/api/consent/revoke` | Revoke it (append-only event log — history is preserved, not overwritten) |
| `GET` | `/api/consent/status` | Current status, derived from the latest event |

### Medical Documents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/documents/upload` | Upload a medical report (PDF/JPG/PNG, max 10MB) — requires `medical_data_processing` consent. OCR'd via Azure Document Intelligence, facts extracted via LLM and stored as `medical_history` memories. Runs synchronously; the response's `status` is already `processed`/`failed` |
| `GET` | `/api/documents` | List the caller's uploaded documents, newest first |
| `GET` | `/api/documents/{id}` | Get one document's status/detail |
| `DELETE` | `/api/documents/{id}` | Delete one document (Mongo record + blob) |
| `POST` | `/api/documents/delete-batch` | Delete a user-selected set of documents (`{"document_ids": [...]}`) |
| `DELETE` | `/api/documents` | "Clear all" — delete every uploaded document for the caller |

All document deletes remove the file and its metadata only — any facts already extracted into `memories` (`medical_history`) are kept, so the assistant doesn't lose context the user already shared.

### Account (export / delete)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/user/export` | JSON dump of everything stored for the caller (`users`, `chat_sessions`, `accepted_plans`, `consents`, `memories`, `episodic_events`, `medical_documents`) |
| `DELETE` | `/api/user/account` | Hard-deletes the caller's documents across every collection (including uploaded medical document blobs). Irreversible. Note: the caller's JWT itself isn't revoked and keeps decoding successfully until it expires — every endpoint it could hit returns empty afterward since the data is actually gone, so there's nothing left to leak, but this isn't full token revocation. |

The frontend covers profile create/edit (with the consent checkbox) and voice/multilingual chat. Export/delete and medical document upload/list/delete are still backend/API only.

---

## Food Database

All food items live in `data/food_db.json`. Each entry follows this schema:

```json
{
  "id": "FOOD_006",
  "food": "paneer",
  "quantity_grams": 100,
  "calories": 265,
  "protein": 18,
  "carbs": 3,
  "fat": 20,
  "diet_types": ["veg", "non_veg"],
  "allergens": ["milk"],
  "regions": ["indian"],
  "meal_types": ["breakfast", "lunch", "dinner"],
  "glycemic_index": "low",
  "medical_tags": ["diabetes_safe"],
  "tags": ["high_protein", "dairy"]
}
```

The food filter agent uses `diet_types`, `allergens`, `medical_tags`, and `glycemic_index` to build a per-user `allowed_foods` list that is injected into the generation prompt. The LLM may only suggest foods from this list. Selection is slot-aware (a share of the list is reserved for breakfast, snack, lunch, and dinner foods) and macro-balanced within each slot, with carb and fat foods ranked by calorie density so grains, roti, rice, oils and nuts are always available — otherwise a high calorie target is physically unreachable.

`quantity_grams` and the nutrient columns are the **only** source of a plan item's numbers: the model chooses a food and a gram amount, and `backend/agents/plan_builder.py` computes calories/protein/carbs/fat as `db_value × grams ÷ quantity_grams`. The model's own arithmetic is never used.

---

## Calorie Calculator

BMR is computed using the **Mifflin-St Jeor equation**:

```
BMR = 10 × weight_kg + 6.25 × height_cm − 5 × age + gender_constant
TDEE = BMR × activity_multiplier
goal_calories = TDEE + goal_adjustment
```

Default macro split is **Protein 30% / Carbs 40% / Fat 30%**. Users with diabetes or PCOS automatically receive a lower-carb split of **Protein 35% / Carbs 30% / Fat 35%**.

Goal adjustments:

| Goal | Adjustment |
|------|-----------|
| Fat loss | −400 kcal |
| Weight / Muscle gain | +325 kcal |
| Maintenance | 0 kcal |
| Manage medical | 0 kcal (condition-specific guidance via RAG) |

---

## User Profile Fields

| Field | Type | Notes |
|-------|------|-------|
| `gender` | `male / female / other` | Used in BMR calculation |
| `age` | int (13–100) | |
| `height_cm` | float | |
| `weight_kg` | float | |
| `activity_level` | `sedentary / lightly_active / moderately_active / very_active / extremely_active` | |
| `diet_type` | `vegetarian / vegan / non_vegetarian` | Drives food filter |
| `goal` | `fat_loss / weight_gain / muscle_gain / maintenance / manage_medical` | |
| `medical_conditions` | list of strings | E.g. `["diabetes", "pcos"]` |
| `allergies` | list of strings | E.g. `["milk", "gluten"]` |
| `bot_name` | string | Personalised assistant name (default: Nova) |

---

## Safety Guarantees

- The LLM **never** computes BMR, TDEE, or macro targets — `backend/tools/calorie_tool.py` is the single source of truth
- The LLM **never** computes a meal plan's numbers either — `backend/agents/plan_builder.py` derives every item's calories and macros from `food_db.json` × grams, sums meals and days, and rescales any day outside ±5% of the target. The plan text the user reads is rendered from that computed plan, not written by the model
- Every generation prompt includes a `USER CONTEXT` block built from the database profile, not from user-supplied text
- The allow-list is enforced deterministically: any selected food that doesn't match `allowed_foods` is dropped before nutrients are computed, and the output guardrail separately checks the prose
- `data/food_db.json` is the macro source of truth; RAG documents are for nutrition knowledge only
- Allergy, diet-type, and medical constraint checks are enforced at the food-filter stage, before the LLM is invoked
- The eval harness's deterministic scorer re-checks every plan item's calories against `food_db.json × grams`, so a regression that lets model arithmetic back in fails the harness

---

## Configuration Reference

All settings are loaded from environment variables (or a `.env` file) via Pydantic Settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` — production refuses to boot with insecure/missing secrets (see Deployment below) |
| `LLM_PROVIDER` | `groq` | Selects the `LLMProvider` implementation (`backend/llm/factory.py`) — `groq` \| `azure_openai` |
| `GROQ_API_KEY` | — | Groq API key (used when `LLM_PROVIDER=groq`) |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Groq model for meal plan generation ("full" profile) |
| `LLM_MODEL_FAST` | `openai/gpt-oss-20b` | Groq model for intent classification ("fast" profile) |
| `AZURE_OPENAI_API_KEY` | — | Azure OpenAI API key (used when `LLM_PROVIDER=azure_openai`) |
| `AZURE_OPENAI_ENDPOINT` | — | Azure OpenAI resource endpoint, e.g. `https://<resource>.openai.azure.com` — **no trailing path** (not `/openai/v1`; see docs/CURRENT_STATE.md for why this bit us) |
| `AZURE_OPENAI_API_VERSION` | `2024-10-21` | Azure OpenAI REST API version |
| `AZURE_OPENAI_DEPLOYMENT_FULL` | `gpt-5-mini` | Deployment name used for meal plan generation ("full" profile) |
| `AZURE_OPENAI_DEPLOYMENT_FAST` | `gpt-5-mini` | Deployment name used for intent classification ("fast" profile) |
| `AZURE_OPENAI_REASONING_MODEL` | `true` | `true` for reasoning models (gpt-5 family: `reasoning_effort`, no `temperature`); set `false` when promoting a classic chat model like gpt-4.1 |
| `AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FULL` | — | Challenger deployment on the same resource, "full" profile (Phase 7; eval-only until promoted) |
| `AZURE_OPENAI_CHALLENGER_DEPLOYMENT_FAST` | — | Challenger deployment, "fast" profile |
| `AZURE_OPENAI_CHALLENGER_REASONING_MODEL` | `false` | Same flag as above, for the challenger |
| `EVAL_JUDGE_PROVIDER` | `azure_openai` | Provider the DeepEval judge is pinned to — deliberately not `LLM_PROVIDER`, so `--compare` arms share one judge |
| `AZURE_STORAGE_CONNECTION_STRING` | — | Azure Blob Storage connection string (medical document uploads) |
| `AZURE_STORAGE_CONTAINER` | `medical-documents` | Blob container name |
| `AZURE_DOC_INTELLIGENCE_ENDPOINT` | — | Azure AI Document Intelligence resource endpoint |
| `AZURE_DOC_INTELLIGENCE_API_KEY` | — | Azure AI Document Intelligence API key |
| `AZURE_SPEECH_KEY` | — | Azure Speech key (an "Azure AI services" multi-service resource works). Empty = voice input disabled, mic button hidden |
| `AZURE_SPEECH_REGION` | — | That resource's region, e.g. `centralindia` |
| `AZURE_TRANSLATOR_KEY` | — | Azure Translator key; empty = reuse `AZURE_SPEECH_KEY` (one multi-service resource covers both) |
| `AZURE_TRANSLATOR_REGION` | — | Empty = reuse `AZURE_SPEECH_REGION` |
| `AZURE_TRANSLATOR_ENDPOINT` | `https://api.cognitive.microsofttranslator.com` | Translator REST endpoint |
| `SPEECH_RECOGNITION_LANGUAGES` | `en-IN,hi-IN,ml-IN,fr-FR` | Server-default candidate locales for spoken-language auto-detection, used when a user hasn't set their own `spoken_languages` (max 4, one locale per language) |
| `MULTILINGUAL_ENABLED` | `true` | Translate-at-the-edges switch. `false` = the pipeline sees raw text and always replies in English |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGODB_DB_NAME` | `nutribot` | Database name |
| `JWT_SECRET` | `change-me-in-production` | JWT signing secret |
| `JWT_EXPIRE_MINUTES` | `10080` (7 days) | Token TTL |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `SENDGRID_API_KEY` | — | SendGrid API key for email delivery |
| `EMAIL_FROM` | — | Sender email address |
| `PINECONE_API_KEY` | — | Pinecone API key |
| `PINECONE_INDEX_NAME` | `nutribot-knowledge` | Pinecone serverless index name |
| `PDF_SOURCE_DIR` | `data` | Directory scanned for nutrition PDFs |
| `RAG_CHUNK_SIZE` | `500` | Token chunk size for PDF ingestion |
| `RAG_CHUNK_OVERLAP` | `50` | Token overlap between chunks |
| `RAG_CORPUS_PATH` | `data/rag_corpus.json` | Local BM25 keyword-search corpus, written by ingestion |
| `RAG_FUSION_POOL_SIZE` | `20` | Candidates pulled from each of dense/sparse search before RRF fusion + reranking |
| `LANGSMITH_TRACING_ENABLED` | `false` | Opt-in LangSmith tracing — off unless both this and `LANGSMITH_API_KEY` are set |
| `LANGSMITH_API_KEY` | — | API key from a [smith.langchain.com](https://smith.langchain.com) account |
| `LANGSMITH_PROJECT` | `nutribot` | LangSmith project name traces are grouped under |
| `FRONTEND_URL` | `http://localhost:3000` | Allowed CORS origin |

---

## Deployment

Deployed as two separate Vercel projects from this repo (interim hosting — the v2 roadmap targets an eventual move to Azure Container Apps / Static Web Apps):

- **Backend** — Root Directory `.`, FastAPI exposed via `[tool.vercel] entrypoint = "backend.main:app"` in `pyproject.toml` (no manual ASGI wrapper needed — Vercel's native FastAPI preset handles routing).
- **Frontend** — Root Directory `frontend/`, Next.js auto-detected.

Both projects read from the same `.env` variable set described above, entered as environment variables in each Vercel project's dashboard (never committed).

> Note: a shared `.vercelignore` at the repo root applies to **both** projects regardless of their Root Directory — don't exclude one project's directory from it, and anchor patterns with a leading `/` if they're only meant to exclude a top-level path (unanchored patterns match at any depth, e.g. inside `backend/`).

The backend refuses to start with `ENVIRONMENT=production` unless `JWT_SECRET`, `MONGODB_URI` (non-localhost), `GROQ_API_KEY`, `PINECONE_API_KEY`, `AZURE_STORAGE_CONNECTION_STRING`, and `AZURE_DOC_INTELLIGENCE_API_KEY` are all set to real, non-default values (`backend/main.py::_validate_production_secrets`) — the Vercel backend project needs `ENVIRONMENT=production` set explicitly for this to apply.

### Docker (local dev / Azure Container Apps prep)

```bash
docker compose up --build
```

Single-service container (backend only — MongoDB Atlas/Pinecone/the LLM provider are already hosted). Builds from the root `Dockerfile`; not part of the Vercel deployment path, this is for local parity and forward-prep for the v2 roadmap's eventual Azure Container Apps target.

---

## Running Tests

```bash
uv run pytest
```

`tests/test_calorie_tool.py`, `tests/test_food_filter.py` and `tests/test_plan_builder.py` cover the safety-critical deterministic modules per the v2 roadmap (calorie math, allergen/diet/medical-condition exclusion, and plan arithmetic/rebalancing). `test_food_filter.py` also asserts, for every golden-set profile, that the food list handed to the model has enough options per meal slot and can physically reach that profile's calorie target. CI (`.github/workflows/ci.yml`) runs this suite on every push/PR to `master` — it deliberately does **not** run the evaluation harness (`backend/eval/`, see below), since that makes real LLM API calls and isn't suited to running on every commit.

To run the evaluation harness manually instead (real API calls, not part of CI):

```bash
uv run python -m backend.eval.runner
```

Runs the 19-case golden set and scores each case both deterministically (plan produced when expected, allergens, allow-list, per-item calories consistent with `food_db.json`, every day within ±15% of the calorie target; plus a per-case line showing what `plan_builder` had to rescale) and via [DeepEval](https://github.com/confident-ai/deepeval) metrics (faithfulness, answer relevancy, and two custom rubrics for medical-safety compliance and completeness) — DeepEval is a dev-only dependency, never installed in production, and its judge calls route through the same `LLMProvider` abstraction as everything else (no separate API key). Judge results gate the exit code for safety-relevant categories (`rag_dependent`, `medical_context`, `allergy_diet_edge_case`); elsewhere they're informational.

To evaluate a challenger model against the primary (Phase 7):

```bash
uv run python -m backend.eval.runner --compare
```

Runs the same golden set on `azure_openai` and `azure_openai_challenger` with the judge pinned to one provider, prints a side-by-side table, writes `eval_compare_results.json`, and exits 0 iff the challenger is promotable (matches or beats the primary's gated-pass count, no safety-gated regressions, no pipeline errors). It probes the challenger first so a missing deployment fails in seconds. Single runs are noisy — run it 2-3 times before promoting. Promotion is a config flip: point `AZURE_OPENAI_DEPLOYMENT_FULL/FAST` at the challenger deployment and set `AZURE_OPENAI_REASONING_MODEL=false` (for a classic model like gpt-4.1); no code changes.

---

## License

MIT
