import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from config import CATEGORIES, DEPARTMENT_ROUTING, GEMINI_MODEL

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

SYSTEM_PROMPT = (
    "You are an invoice classification assistant.\n"
    "Your task is to read the provided invoice and classify it into EXACTLY ONE of the following categories.\n"
    "Respond with ONLY the category name — no punctuation, no explanation, no extra text.\n\n"
    "Allowed categories:\n"
    + "\n".join(f"- {c}" for c in CATEGORIES)
)


def _load_pdf_parts(file_path: Path) -> list:
    return [
        types.Part.from_bytes(data=file_path.read_bytes(), mime_type="application/pdf"),
        types.Part.from_text(text="Classify this invoice."),
    ]


def _load_image_parts(file_path: Path) -> list:
    return [
        types.Part.from_bytes(data=file_path.read_bytes(), mime_type="image/png"),
        types.Part.from_text(text="Classify this invoice."),
    ]


def _load_docx_parts(file_path: Path) -> list:
    from docx2pdf import convert

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_pdf = Path(tmp_dir) / (file_path.stem + ".pdf")
        convert(str(file_path), str(tmp_pdf))
        pdf_bytes = tmp_pdf.read_bytes()

    return [
        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
        types.Part.from_text(text="Classify this invoice."),
    ]


def _parse_response(raw: str) -> str:
    cleaned = raw.strip().rstrip(".").strip()
    lower_map = {c.lower(): c for c in CATEGORIES}
    return lower_map.get(cleaned.lower(), "UNKNOWN")


def classify_invoice(file_path: str | Path) -> dict:
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        contents = _load_pdf_parts(file_path)
    elif ext == ".png":
        contents = _load_image_parts(file_path)
    elif ext == ".docx":
        contents = _load_docx_parts(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            max_output_tokens=1024,
        ),
    )

    raw_text = response.text or ""
    if not raw_text:
        print(f"  [warn] Empty response from Gemini for {file_path.name}. Full response: {response}")

    predicted = _parse_response(raw_text)
    department = DEPARTMENT_ROUTING.get(predicted, "Unknown Department")

    return {
        "filename": file_path.name,
        "predicted_category": predicted,
        "department": department,
        "raw_response": raw_text.strip(),
    }
