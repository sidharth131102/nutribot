"""Medical-fact extraction from OCR'd document text (v2 roadmap Phase 4).

Invariant 5: the system extracts/reports medical facts, it never diagnoses.
The prompt below is written to enforce that -- only verbatim-or-near-verbatim
stated facts are extracted, never an inference drawn from them.

Mirrors backend/memory/extraction.py's shape, but parses a JSON *array* (one
document can yield many facts) instead of a single object.
"""
import json
import logging
import re

from backend.db.mongo import UserScopedRepo
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider
from backend.models.medical_document import ExtractedMedicalFact

logger = logging.getLogger("nutribot.documents.extraction")

# Long multi-page reports get truncated to this many characters before being
# sent to the LLM -- a known Phase-4 limitation, not a bug.
MAX_DOCUMENT_CHARS = 12000

EXTRACTION_SYSTEM_PROMPT = """You extract ONLY facts that are explicitly stated in a medical document.
You are not a doctor and must never diagnose, infer, or interpret anything not written
verbatim or near-verbatim in the text -- e.g. extract "HbA1c 7.2 on 2026-01-15" but never
add "this indicates diabetes" unless the document itself states a diagnosis in those terms.

Extract only: stated diagnoses/conditions with dates if given, lab values with dates,
prescribed medications with dosage, stated allergies. Ignore doctor's narrative reasoning,
differential diagnoses, or anything hedged/possible/ruled-out.

Reply with ONLY a JSON array, no other text. Each item:
{"fact": "<short third-person factual statement>", "confidence": 0.0-1.0}
If nothing extractable, reply exactly: []"""


def _extract_json_array(text: str) -> list | None:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


async def extract_medical_facts(document_text: str) -> list[ExtractedMedicalFact]:
    """Text in, facts out -- no Mongo writes here, keeps this testable in isolation."""
    truncated = document_text[:MAX_DOCUMENT_CHARS]
    try:
        result = await get_provider().generate(
            messages=[
                Message(role="system", content=EXTRACTION_SYSTEM_PROMPT),
                Message(role="user", content=truncated),
            ],
            config=GenerationConfig(profile="full", temperature=0, max_tokens=800),
        )
        parsed = _extract_json_array(result.text)
        if not parsed:
            return []
        facts = []
        for item in parsed:
            if isinstance(item, dict) and item.get("fact"):
                facts.append(ExtractedMedicalFact(**item))
        return facts
    except Exception:
        logger.exception("Medical document fact extraction failed")
        return []


async def process_document(repo: UserScopedRepo, document_id: str, raw_text: str) -> int:
    """Orchestrates extraction -> memory writes -> status update. Returns fact count."""
    facts = await extract_medical_facts(raw_text)
    for f in facts:
        await repo.add_memory_fact(f.fact, "medical_history", source="document_extraction", confidence=f.confidence)
    return len(facts)
