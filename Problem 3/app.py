import json
import os
import re
from datetime import date

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="Work Permit Validator", layout="centered")
st.title("Work Permit Validator")
st.write("Upload a PDF document to check if it is a valid German work permit.")


def build_prompt() -> str:
    today_str = date.today().strftime("%d.%m.%Y")
    return f"""Analysiere dieses deutsche Dokument als Aufenthaltstitel/Arbeitserlaubnis.
Heutiges Datum (Referenzdatum): {today_str}

Prüfe folgendes:
1. Ist es ein Aufenthaltstitel oder ein Dokument, das Erwerbstätigkeit erlaubt?
2. Was ist das Ablaufdatum (z.B. "Gültig bis", "Gültigkeitsdatum")?
3. Stehen in den Bemerkungen Einschränkungen wie "Erwerbstätigkeit nicht gestattet"?

Regeln:
- INVALID wenn: kein Aufenthaltstitel / kein Arbeitsdokument
- INVALID wenn: Ablaufdatum vor dem {today_str} (heutiges Datum)
- INVALID wenn: Bemerkungen enthalten "Erwerbstätigkeit nicht gestattet" oder ähnliche Einschränkungen
- VALID sonst

Antworte NUR mit diesem JSON (kein Markdown, kein Text davor oder danach):
{{"status": "VALID", "valid_until": "DD.MM.YYYY", "reason": "kurze Begründung"}}
oder
{{"status": "INVALID", "valid_until": null, "reason": "kurze Begründung"}}"""


def analyze_permit(pdf_bytes: bytes) -> dict:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = build_prompt()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            types.Part.from_text(text=prompt),
        ],
    )

    raw = response.text.strip()
    # Strip markdown code fences if Gemini wraps the JSON
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


uploaded_file = st.file_uploader("Upload work permit PDF", type=["pdf"])

if uploaded_file is not None:
    if not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY is not set. Create a .env file with your API key.")
    else:
        with st.spinner("Analyzing document..."):
            try:
                pdf_bytes = uploaded_file.read()
                result = analyze_permit(pdf_bytes)

                status = result.get("status", "").upper()
                valid_until = result.get("valid_until")
                reason = result.get("reason", "")

                if status == "VALID":
                    st.success("VALID Work Permit")
                    if valid_until:
                        st.metric(label="Valid until", value=valid_until)
                    if reason:
                        st.caption(reason)
                else:
                    st.error("INVALID Work Permit")
                    if reason:
                        st.write(f"**Reason:** {reason}")

            except json.JSONDecodeError:
                st.warning("Could not parse the model response as JSON.")
                st.code(response.text if "response" in dir() else "No response available")
            except Exception as e:
                st.error(f"Error: {e}")
