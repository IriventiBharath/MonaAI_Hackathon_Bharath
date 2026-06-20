"""Agent 3: Document Classifier — identifies document type via Gemini vision."""
import logging
from enum import Enum

from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_SYSTEM = """You are a document classification assistant. Classify the document into exactly one
of the following categories:

CV           - curriculum vitae / resume
WORK_PERMIT  - work permit / employment authorization
RESIDENCE_PERMIT - residence permit / residency card / national ID showing residence rights
CRIMINAL_RECORD  - criminal record check / police clearance / background check
UNKNOWN      - none of the above

The document may be in any language.
Reply with ONLY the single category label exactly as written above (e.g. CV, WORK_PERMIT, RESIDENCE_PERMIT, CRIMINAL_RECORD, or UNKNOWN). No other text."""

# Maps keywords in Gemini's response → canonical DocumentType value
_KEYWORD_MAP = {
    "CV": "CV",
    "RESUME": "CV",
    "CURRICULUM": "CV",
    "WORK_PERMIT": "WORK_PERMIT",
    "WORK PERMIT": "WORK_PERMIT",
    "EMPLOYMENT": "WORK_PERMIT",
    "RESIDENCE_PERMIT": "RESIDENCE_PERMIT",
    "RESIDENCE PERMIT": "RESIDENCE_PERMIT",
    "RESIDENCY": "RESIDENCE_PERMIT",
    "CRIMINAL_RECORD": "CRIMINAL_RECORD",
    "CRIMINAL RECORD": "CRIMINAL_RECORD",
    "POLICE CLEARANCE": "CRIMINAL_RECORD",
    "BACKGROUND CHECK": "CRIMINAL_RECORD",
    # common abbreviations Gemini uses
    "CR": "CRIMINAL_RECORD",
    "RP": "RESIDENCE_PERMIT",
    "WP": "WORK_PERMIT",
}


class DocumentType(str, Enum):
    CV = "CV"
    WORK_PERMIT = "WORK_PERMIT"
    RESIDENCE_PERMIT = "RESIDENCE_PERMIT"
    CRIMINAL_RECORD = "CRIMINAL_RECORD"
    UNKNOWN = "UNKNOWN"


def _parse_label(raw: str) -> DocumentType:
    upper = raw.upper().strip()
    # Exact match first
    try:
        return DocumentType(upper)
    except ValueError:
        pass
    # Keyword scan
    for keyword, value in _KEYWORD_MAP.items():
        if keyword in upper:
            return DocumentType(value)
    return DocumentType.UNKNOWN


def classify(pdf_bytes: bytes, api_key: str = GEMINI_API_KEY) -> DocumentType:
    """Send PDF directly to Gemini (vision) and classify its document type."""
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            genai_types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            genai_types.Part(text="Classify this document."),
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            max_output_tokens=1024,
        ),
    )
    raw = (response.text or "").strip()
    logger.info("Classifier raw response: %r", raw)
    return _parse_label(raw)
