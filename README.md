# NutriBot

Production-ready AI nutrition assistant with deterministic nutrition calculations, LangChain tool boundaries, LangGraph orchestration, RAG knowledge injection, CAG runtime context, and strict validation before returning structured meal plans.

## Architecture

- `backend/`: FastAPI API, Pydantic schemas, async database setup, SQLAlchemy PostgreSQL-ready models.
- `agent/`: LangGraph flow with calculation, retrieval, CAG, generation, validation, and retry nodes.
- `tools/`: deterministic calculator, LangChain tool wrapper, JSON food DB loader/filter, and validation engine.
- `rag/`: PDF ingestion, metadata-aware FAISS retrieval, and deterministic fallback knowledge.
- `data/food_db.json`: single source of truth for foods and macro values.
- `frontend/`: Next.js App Router UI with profile controls, chat request, macro chart, and meal cards.

## Non-negotiable safety rules implemented

- The LLM does not calculate BMR, TDEE, target calories, or protein. `tools/calculator.py` owns those values.
- Every generation prompt includes `USER CONTEXT` from `agent/context.py`.
- RAG documents are injected as `RETRIEVED KNOWLEDGE`.
- The prompt only permits foods inside CAG `allowed_foods`.
- `data/food_db.json` is the macro source of truth; RAG is for nutrition knowledge, not macros.
- `tools/validator.py` rejects invalid foods, foods outside `allowed_foods`, allergy/diet/medical violations, calorie misses, protein misses, fat percentage misses, and macro inconsistency by recomputing totals from the JSON DB.
- LangGraph retries invalid generations up to `NUTRIBOT_MAX_GENERATION_RETRIES` times.
- API responses are structured JSON through Pydantic response models.

## Backend

```bash
pip install -e ".[dev]"
$env:NUTRIBOT_OPENAI_API_KEY="..."
python main.py
```

Useful environment variables:

```bash
NUTRIBOT_DATABASE_URL=postgresql+asyncpg://user:password@host:5432/nutribot
NUTRIBOT_OPENAI_API_KEY=...
NUTRIBOT_MODEL_NAME=gpt-4o-mini
NUTRIBOT_MAX_GENERATION_RETRIES=3
NUTRIBOT_FOOD_DB_PATH=data/food_db.json
NUTRIBOT_RAG_SOURCE_DIR=rag/source_docs
NUTRIBOT_VECTOR_STORE_PATH=rag/faiss_index
```

Endpoints:

- `POST /chat`
- `POST /generate-plan`
- `GET /user-profile?user_id=1`
- `POST /user-profile`
- `POST /save-plan`
- `GET /health`

## Frontend

```bash
cd frontend
npm install
$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
npm run dev
```

## RAG ingestion

Place nutrition PDFs in:

```text
rag/source_docs/
  diabetes_guidelines.pdf
  pcos_nutrition.pdf
  thyroid_diet.pdf
  hypertension_diet.pdf
  indian_diet_guidelines.pdf
  protein_requirements.pdf
```

Then build the FAISS index:

```python
from rag.ingest import ingest_documents

ingest_documents("rag/source_docs", "rag/faiss_index")
```

Each chunk gets metadata with `source`, `type`, and `condition`. The retriever supports semantic search and condition metadata filtering. The deterministic fallback corpus is only used when no FAISS index exists.

## Food DB

Foods live in `data/food_db.json` with exact macro values and safety metadata:

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

The LLM may only use foods from the filtered CAG `allowed_foods` list, and validation cross-checks every item against this file.

## Verification

```bash
pytest
```
