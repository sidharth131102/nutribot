"""Azure Document Intelligence wrapper. The only file allowed to import
azure.ai.documentintelligence.

Uses the prebuilt-read model (OCR + plain text) rather than a custom-trained
model -- no training data exists, and generic medical reports vary too much
in layout for a custom model to be worth building at this phase. Bytes in,
text out -- no LLM calls and no Mongo calls happen here.
"""
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential

from backend.config import Settings


async def extract_text(settings: Settings, content: bytes, content_type: str) -> str:
    """Runs OCR against the document bytes, returns the concatenated plain text."""
    async with DocumentIntelligenceClient(
        endpoint=settings.azure_doc_intelligence_endpoint,
        credential=AzureKeyCredential(settings.azure_doc_intelligence_api_key),
    ) as client:
        poller = await client.begin_analyze_document(
            "prebuilt-read",
            AnalyzeDocumentRequest(bytes_source=content),
        )
        result = await poller.result()
        return result.content or ""
