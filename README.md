# NutriBot

**NutriBot** is a production-grade AI nutrition assistant that combines a 6-agent LangGraph pipeline, deterministic calorie calculations, RAG-powered nutrition knowledge, and a personalized food database to generate safe, medically-aware meal plans via a conversational interface.

---

## Features

- **Multi-agent LangGraph pipeline** — 6 specialized agents (Profile, Intent, Calorie, RAG, Food, MealPlan) orchestrated in a stateful graph with conditional routing
- **Deterministic nutrition math** — BMR and TDEE are always computed via the Mifflin-St Jeor formula; the LLM never invents calorie numbers
- **Condition-aware macro splits** — automatic carb-to-protein rebalancing for users with diabetes or PCOS
- **RAG knowledge injection** — Pinecone vector store with integrated embeddings (`llama-text-embed-v2`, no local embedding model needed), seeded from medical PDF documents (diabetes, PCOS, thyroid, hypertension, etc.)
- **Curated food database** — `data/food_db.json` is the single source of truth for macro values; foods carry allergen, medical, glycemic, region, and diet-type metadata
- **Context-Augmented Generation (CAG)** — every LLM prompt is pre-loaded with the user's profile, calorie targets, RAG chunks, and an approved food list so the model cannot hallucinate out-of-scope items
- **Intent classification** — lightweight fast model routes each message to the correct pipeline branch before any heavy generation occurs
- **Email delivery** — accepted meal plans can be sent to the user via SendGrid
- **Auth** — JWT bearer tokens with email/password registration and Google OAuth 2.0 sign-in
- **Chat history & plan memory** — conversations and accepted plans are persisted in MongoDB and injected into subsequent turns
- **Next.js frontend** — chat interface with macro charts, meal plan cards, and an accept/modify panel

---

## Architecture

```
profile → intent → [route] → calorie? → rag? → food? → meal_plan → END
```

### Agent pipeline

| # | Agent | Responsibility |
|---|-------|---------------|
| 1 | **Profile** | Loads user profile from MongoDB, builds the CAG context block, fetches chat history and previous accepted plans |
| 2 | **Intent** | Classifies the message into one of six intents using a fast LLM |
| 3 | **Calorie** | Runs the Mifflin-St Jeor calculator tool; never delegated to the LLM |
| 4 | **RAG** | Retrieves relevant chunks from Pinecone with optional condition-metadata filtering |
| 5 | **Food** | Filters `food_db.json` by diet type, allergens, medical tags, and goal to produce an `allowed_foods` CAG list |
| 6 | **MealPlan** | Synthesises all upstream context and generates a structured meal plan or conversational reply using a large Groq model |

### Intent routing

| Intent | Calorie | RAG | Food |
|--------|---------|-----|------|
| `MEAL_PLAN_REQUEST` | ✅ | ✅ | ✅ |
| `PLAN_MODIFICATION` | ✅ | ✅ | ✅ |
| `CALORIE_CALCULATION` | ✅ | ✗ | ✗ |
| `ROUTINE_REQUEST` | ✗ | ✅ | ✅ |
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
| LLM (generation) | Groq — `openai/gpt-oss-120b`, behind a provider abstraction (`backend/llm/`) |
| LLM (intent) | Groq — `openai/gpt-oss-20b` |
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
- Groq API key (free tier available at [console.groq.com](https://console.groq.com))

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

This parses each PDF, chunks the text (500-token chunks, 50-token overlap), and upserts into Pinecone — embedding happens server-side via the index's integrated model, no separate embedding API key required. If no PDFs are ingested, RAG-dependent responses will say clinical guidelines are unavailable rather than falling back to any built-in corpus (none currently exists).

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
| `POST` | `/api/profile/create` | Create profile |
| `PUT` | `/api/profile/update` | Update profile |

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat/message` | Send a message; returns agent response and optional proposed plan |
| `GET` | `/api/chat/history` | Fetch session message history |
| `GET` | `/api/chat/sessions` | List all sessions for the user |

### Plans

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/plans/accept` | Accept and persist a proposed meal plan; also triggers the SendGrid email |
| `GET` | `/api/plans/saved` | List previously accepted plans |

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

The food filter agent uses `diet_types`, `allergens`, `medical_tags`, and `regions` to build a per-user `allowed_foods` list that is injected into the generation prompt. The LLM may only suggest foods from this list.

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
- Every generation prompt includes a `USER CONTEXT` block built from the database profile, not from user-supplied text
- The generation prompt only permits foods present in the CAG `allowed_foods` list
- `data/food_db.json` is the macro source of truth; RAG documents are for nutrition knowledge only
- Allergy, diet-type, and medical constraint checks are enforced at the food-filter stage, before the LLM is invoked
- The allow-list is enforced via the generation prompt only — there is currently no deterministic post-generation check that the model's output actually stayed within `allowed_foods`

---

## Configuration Reference

All settings are loaded from environment variables (or a `.env` file) via Pydantic Settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` — production refuses to boot with insecure/missing secrets (see Deployment below) |
| `GROQ_API_KEY` | — | Groq API key |
| `LLM_PROVIDER` | `groq` | Selects the `LLMProvider` implementation (`backend/llm/factory.py`) |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Model used for meal plan generation ("full" profile) |
| `LLM_MODEL_FAST` | `openai/gpt-oss-20b` | Model used for intent classification ("fast" profile) |
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
| `FRONTEND_URL` | `http://localhost:3000` | Allowed CORS origin |

---

## Deployment

Deployed as two separate Vercel projects from this repo (interim hosting — the v2 roadmap targets an eventual move to Azure Container Apps / Static Web Apps):

- **Backend** — Root Directory `.`, FastAPI exposed via `[tool.vercel] entrypoint = "backend.main:app"` in `pyproject.toml` (no manual ASGI wrapper needed — Vercel's native FastAPI preset handles routing).
- **Frontend** — Root Directory `frontend/`, Next.js auto-detected.

Both projects read from the same `.env` variable set described above, entered as environment variables in each Vercel project's dashboard (never committed).

> Note: a shared `.vercelignore` at the repo root applies to **both** projects regardless of their Root Directory — don't exclude one project's directory from it, and anchor patterns with a leading `/` if they're only meant to exclude a top-level path (unanchored patterns match at any depth, e.g. inside `backend/`).

The backend refuses to start with `ENVIRONMENT=production` unless `JWT_SECRET`, `MONGODB_URI` (non-localhost), `GROQ_API_KEY`, and `PINECONE_API_KEY` are all set to real, non-default values (`backend/main.py::_validate_production_secrets`) — the Vercel backend project needs `ENVIRONMENT=production` set explicitly for this to apply.

### Docker (local dev / Azure Container Apps prep)

```bash
docker compose up --build
```

Single-service container (backend only — MongoDB Atlas/Pinecone/Groq are already hosted). Builds from the root `Dockerfile`; not part of the Vercel deployment path, this is for local parity and forward-prep for the v2 roadmap's eventual Azure Container Apps target.

---

## Running Tests

```bash
uv run pytest
```

`tests/test_calorie_tool.py` and `tests/test_food_filter.py` cover the two safety-critical modules per the v2 roadmap (deterministic calorie math, and allergen/diet/medical-condition exclusion). CI (`.github/workflows/ci.yml`) runs this suite on every push/PR to `master` — it deliberately does **not** run the evaluation harness (`backend/eval/`, see below), since that makes real Groq API calls against a rate-limited account and isn't suited to running on every commit.

To run the evaluation harness manually instead (real API calls, not part of CI):

```bash
uv run python -m backend.eval.runner
```

---

## License

MIT
