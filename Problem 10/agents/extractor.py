"""Agent 4: Information Extractor — pulls structured fields via Gemini vision."""
import json
import logging
from dataclasses import dataclass, field

from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GEMINI_MODEL
from agents.classifier import DocumentType

logger = logging.getLogger(__name__)

_SYSTEM_BASE = """You are a document data-extraction assistant. Extract the requested fields from
the document. The document may be in any language — always respond in English.
Return ONLY a valid JSON object with the specified keys. Use null for any field you cannot find.
All dates must be in ISO 8601 format (YYYY-MM-DD)."""

_PROMPTS: dict[DocumentType, str] = {
    DocumentType.CV: """Extract these fields and return as JSON:
{
  "holder_name": "full name of the person",
  "nationality": "nationality or citizenship",
  "employment_eligibility_markers": ["list of any phrases indicating work authorization"]
}""",
    DocumentType.WORK_PERMIT: """Extract these fields and return as JSON:
{
  "holder_name": "full name on the permit",
  "permit_number": "document/permit number",
  "expiry_date": "YYYY-MM-DD",
  "issuing_country": "country that issued the permit"
}""",
    DocumentType.RESIDENCE_PERMIT: """Extract these fields and return as JSON:
{
  "holder_name": "full name on the permit",
  "permit_number": "document/permit number",
  "expiry_date": "YYYY-MM-DD",
  "issuing_country": "country that issued the permit"
}""",
    DocumentType.CRIMINAL_RECORD: """Extract these fields and return as JSON:
{
  "holder_name": "full name of the subject",
  "issue_date": "YYYY-MM-DD (date the report was issued)",
  "jurisdiction": "country or authority that issued the report"
}""",
}


@dataclass
class ExtractionResult:
    doc_type: DocumentType
    filename: str
    data: dict = field(default_factory=dict)
    error: str = ""


def extract(filename: str, pdf_bytes: bytes, doc_type: DocumentType,
            api_key: str = GEMINI_API_KEY) -> ExtractionResult:
    if doc_type == DocumentType.UNKNOWN:
        return ExtractionResult(doc_type=doc_type, filename=filename,
                                error="Document type is UNKNOWN — skipping extraction")

    client = genai.Client(api_key=api_key)
    prompt = _PROMPTS[doc_type]

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            genai_types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            genai_types.Part(text=prompt),
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=_SYSTEM_BASE,
            max_output_tokens=1024,
        ),
    )
    raw = (response.text or "").strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
        return ExtractionResult(doc_type=doc_type, filename=filename, data=data)
    except json.JSONDecodeError:
        logger.warning("Extractor returned non-JSON for %s: %s", filename, raw[:120])
        return ExtractionResult(doc_type=doc_type, filename=filename,
                                error=f"Parse error: {raw[:120]}")
