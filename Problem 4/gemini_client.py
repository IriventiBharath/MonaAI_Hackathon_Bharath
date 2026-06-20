import io
import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

_MODEL = "gemini-2.5-flash"
_CERT_PROMPT_PATH = Path(__file__).parent / "Certificates" / "prompt.md"

_EXTRACTION_PROMPT = """Extract structured data from this CV text and return a single valid JSON object.

Fields to extract:
- name (string)
- title (string, job title/role)
- contact (object with: email, phone, github_url, linkedin_url — use null if not found)
- skills (array of strings)
- profile_summary (string)
- experience (array of objects, each with: title, company, dates, bullets[])
- education (array of objects, each with: degree, institution, dates)
- certifications (array of strings)
- languages (array of strings)

CV Text:
{raw_text}

Return ONLY the JSON object. No markdown, no explanation."""

_ANALYSIS_PROMPT = """You are a CV credibility analyst. Your job is to detect fabricated or exaggerated CVs by analysing the internal consistency of the CV itself.

CV Data:
{cv_json}

Primary analysis — focus 90% of your scoring here:
1. Skills vs Experience: Do the skills listed actually appear in the job descriptions? Are skills claimed that were never used in any role?
2. Timeline consistency: Do the dates add up? Are there overlapping jobs, implausible gaps, or suspiciously short tenures that still claim deep expertise?
3. Seniority progression: Does the career path make sense (e.g. jumping from intern to CTO in 2 years is suspicious)?
4. Skills vs Education: Does the education background support the technical depth claimed?
5. Buzzword density: Are the job bullet points vague and keyword-stuffed with no concrete outcomes or numbers?
6. Certifications: Do the certifications align with the skills and experience, or do they seem bolted on?

Secondary — only if GitHub or LinkedIn URLs are present in the CV, call fetch_url on each:
- GitHub: read the profile and note whether the languages/repos match the claimed skills.
- LinkedIn: the page requires login so you will only get a reachability result. A reachable LinkedIn URL just confirms the account exists — do NOT treat it as a signal either way. Only flag LinkedIn if fetch_url returns a 404 or error (broken link = potential red flag).

Return a JSON object with:
- bullshit_score: integer 0-100 (0 = fully credible, 100 = completely fabricated)
- verdict: one of "Credible", "Slightly Suspicious", "Suspicious", "Highly Suspicious"
- explanation: 2-3 sentences summarizing your assessment, focused on the CV content itself
- red_flags: array of specific concerns found in the CV (strings)
- positive_signals: array of things that check out (strings)
- link_results: object mapping each URL checked to its status

Return ONLY the JSON object. No markdown fences."""


def _clean_json(text: str) -> str:
    text = text.strip()
    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_cv_structure(raw_text: str) -> dict:
    model = genai.GenerativeModel(
        _MODEL,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    prompt = _EXTRACTION_PROMPT.format(raw_text=raw_text)
    try:
        response = model.generate_content(prompt)
        return json.loads(_clean_json(response.text))
    except Exception:
        # Retry without JSON mime type in case model doesn't support it
        model_fallback = genai.GenerativeModel(
            _MODEL,
            generation_config=genai.GenerationConfig(temperature=0.1),
        )
        response = model_fallback.generate_content(prompt)
        try:
            return json.loads(_clean_json(response.text))
        except json.JSONDecodeError:
            return {"raw_text": raw_text, "parse_error": "Could not extract structured data"}


def analyze_cv(cv_data: dict) -> dict:
    link_results: dict[str, str] = {}

    def fetch_url(url: str) -> str:
        """Fetch the text content of a URL to verify claims made in a CV.
        Use this tool for every GitHub and LinkedIn URL found in the CV contact section.

        Args:
            url: The full URL to fetch (must start with http:// or https://)
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        # LinkedIn blocks scraping — just check if the profile URL exists
        if "linkedin.com" in url:
            try:
                resp = requests.get(url, timeout=10, headers=headers, allow_redirects=True)
                slug = url.rstrip("/").split("/")[-1]
                # 200 = login wall, 999 = LinkedIn anti-bot block — both mean the profile exists
                if resp.status_code in (200, 999):
                    link_results[url] = "functional"
                    return (
                        f"LinkedIn profile URL is reachable (slug: '{slug}'). "
                        "Content is behind a login wall and cannot be read."
                    )
                else:
                    link_results[url] = f"not reachable (HTTP {resp.status_code})"
                    return f"LinkedIn profile returned HTTP {resp.status_code} — profile likely does not exist."
            except requests.exceptions.Timeout:
                link_results[url] = "not reachable (timeout)"
                return "ERROR: LinkedIn request timed out"
            except Exception as e:
                link_results[url] = "not reachable (error)"
                return f"ERROR reaching LinkedIn: {e}"

        try:
            resp = requests.get(url, timeout=10, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Remove script/style noise
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)[:4000]
                link_results[url] = "functional"
                return text
            else:
                link_results[url] = f"not reachable (HTTP {resp.status_code})"
                return f"URL returned HTTP {resp.status_code}"
        except requests.exceptions.Timeout:
            link_results[url] = "not reachable (timeout)"
            return "ERROR: Request timed out"
        except requests.exceptions.ConnectionError:
            link_results[url] = "not reachable (connection error)"
            return "ERROR: Could not connect"
        except Exception as e:
            link_results[url] = f"not reachable ({type(e).__name__})"
            return f"ERROR: {e}"

    analysis_model = genai.GenerativeModel(
        _MODEL,
        tools=[fetch_url],
        generation_config=genai.GenerationConfig(temperature=0.2),
    )

    prompt = _ANALYSIS_PROMPT.format(cv_json=json.dumps(cv_data, indent=2))

    try:
        chat = analysis_model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(prompt)
        result = json.loads(_clean_json(response.text))
    except json.JSONDecodeError:
        # Gemini returned non-JSON — build a minimal result
        result = {
            "bullshit_score": -1,
            "verdict": "Analysis Error",
            "explanation": response.text[:500],
            "red_flags": [],
            "positive_signals": [],
            "link_results": {},
        }
    except Exception as e:
        result = {
            "bullshit_score": -1,
            "verdict": "Analysis Error",
            "explanation": str(e),
            "red_flags": [],
            "positive_signals": [],
            "link_results": {},
        }

    # Merge our locally tracked link results (ground truth from actual requests)
    if link_results:
        result["link_results"] = link_results

    return result


def analyze_certificate(image_bytes: bytes) -> dict:
    from datetime import date
    today = date.today().isoformat()
    base_prompt = _CERT_PROMPT_PATH.read_text(encoding="utf-8")
    prompt_text = f"Today's date is {today}.\n\n{base_prompt}"
    pil_image = Image.open(io.BytesIO(image_bytes))

    model = genai.GenerativeModel(
        _MODEL,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    try:
        response = model.generate_content([prompt_text, pil_image])
        result = json.loads(_clean_json(response.text))
    except Exception:
        model_fallback = genai.GenerativeModel(
            _MODEL,
            generation_config=genai.GenerationConfig(temperature=0.1),
        )
        response = model_fallback.generate_content([prompt_text, pil_image])
        try:
            result = json.loads(_clean_json(response.text))
        except json.JSONDecodeError:
            return {
                "document_type": "Unknown",
                "extracted_information": {},
                "flags": [],
                "risk_score": -1,
                "risk_level": "Analysis Error",
                "reasoning": response.text[:500],
                "is_date_invalid": False,
            }

    # Hard rule: expired or future-dated certificate = 100% fraud
    if result.get("is_date_invalid"):
        result["risk_score"] = 100
        result["risk_level"] = "High Risk"
        date_flag = f"EXPIRED / INVALID DATE: This certificate is not valid as of {today}."
        flags = result.get("flags", [])
        if date_flag not in flags:
            flags.insert(0, date_flag)
        result["flags"] = flags

    return result
