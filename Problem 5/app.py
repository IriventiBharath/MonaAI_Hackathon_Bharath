import json
import os
import re
import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

JOBS = [
    {
        "id": "hiring_manager",
        "title": "Hiring Manager — People & Talent",
        "subtitle": "Own end-to-end hiring for a fast-scaling AI product company",
        "pdf": "job_offer_1_hiring_manager.pdf",
    },
    {
        "id": "gtm_engineer",
        "title": "Go-to-Market (GTM) Engineer",
        "subtitle": "Where revenue meets engineering: build the systems that scale sales",
        "pdf": "job_offer_2_gtm_engineer.pdf",
    },
    {
        "id": "fde",
        "title": "Forward Deployed Engineer (FDE)",
        "subtitle": "Embed with customers and turn their hardest problems into shipped AI solutions",
        "pdf": "job_offer_3_forward_deployed_engineer.pdf",
    },
]

LIKERT_OPTIONS = [
    "1 — Unsatisfied",
    "2",
    "3 — Neutral",
    "4",
    "5 — Satisfied",
]


def get_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def read_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def generate_questions(pdf_text: str, api_key: str) -> tuple[list[str], list[list[str]]]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = (
        "You are an interview support agent for MONA AI.\n\n"
        "Below is a job posting. At the bottom you will find a 'For the agent' section "
        "with specific instructions on what to probe and what red flags to watch for.\n\n"
        "Generate exactly 3 interview questions strictly following those instructions. "
        "For each question also provide 4–6 TECHNICAL keywords or short technical terms/phrases "
        "that a strong candidate answer should contain. These keywords will be shown to a "
        "non-technical hiring manager so they can listen for them during the interview — "
        "choose specific technical jargon, tool names, methodologies, or concepts that only "
        "someone with genuine hands-on experience would naturally say. Avoid generic words.\n\n"
        "Return ONLY a JSON array with exactly 3 objects. No preamble, no markdown fences.\n"
        'Format: [{"question": "...", "keywords": ["kw1", "kw2", ...]}, ...]\n\n'
        "--- JOB POSTING ---\n"
        f"{pdf_text}"
    )
    response = model.generate_content(prompt)
    return parse_response(response.text)


def parse_response(raw: str) -> tuple[list[str], list[list[str]]]:
    try:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            questions = [item["question"] for item in data[:3]]
            keywords = [item.get("keywords", []) for item in data[:3]]
            return questions, keywords
    except Exception:
        pass
    # fallback: parse numbered list, no keywords
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    questions = []
    for line in lines:
        cleaned = re.sub(r"^\d+[\.\)]\s*", "", line)
        if cleaned:
            questions.append(cleaned)
    questions = questions[:3]
    return questions, [[] for _ in questions]


def init_state():
    defaults = {
        "page": "home",
        "selected_job": None,
        "questions": [],
        "keywords": [],
        "q_index": 0,
        "answers": [],
        "done": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def go_home():
    st.session_state.page = "home"
    st.session_state.selected_job = None
    st.session_state.questions = []
    st.session_state.keywords = []
    st.session_state.q_index = 0
    st.session_state.answers = []
    st.session_state.done = False


def select_job(job: dict):
    st.session_state.page = "detail"
    st.session_state.selected_job = job
    st.session_state.questions = []
    st.session_state.keywords = []
    st.session_state.q_index = 0
    st.session_state.answers = []
    st.session_state.done = False


def render_home():
    st.markdown(
        "<h1 style='color:#C0392B;'>MONA AI</h1>"
        "<h3 style='margin-top:-12px; color:#555;'>Interview Support Agent</h3>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.markdown("**Select a job posting to begin the interview question flow.**")
    st.markdown("")

    for job in JOBS:
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{job['title']}**")
                st.caption(job["subtitle"])
            with col2:
                if st.button("Open →", key=f"btn_{job['id']}"):
                    select_job(job)
                    st.rerun()


def render_detail(api_key: str):
    job = st.session_state.selected_job

    if st.button("← Back to listings"):
        go_home()
        st.rerun()

    st.markdown(
        f"<h2 style='color:#C0392B;'>{job['title']}</h2>"
        f"<p style='color:#555; margin-top:-8px;'>{job['subtitle']}</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    if not st.session_state.questions:
        with st.spinner("Generating interview questions with Gemini 2.5 Flash…"):
            pdf_path = os.path.join(os.path.dirname(__file__), job["pdf"])
            pdf_text = read_pdf_text(pdf_path)
            questions, keywords = generate_questions(pdf_text, api_key)
        st.session_state.questions = questions
        st.session_state.keywords = keywords
        st.session_state.q_index = 0
        st.rerun()
        return

    if st.session_state.done:
        render_summary()
        return

    render_question()


def render_question():
    idx = st.session_state.q_index
    questions = st.session_state.questions
    keywords = st.session_state.keywords
    total = len(questions)

    st.markdown(f"**Question {idx + 1} of {total}**")

    q_col, kw_col = st.columns([3, 2])

    with q_col:
        st.markdown(f"> {questions[idx]}")

    with kw_col:
        st.markdown("**Expected Keywords**")
        kws = keywords[idx] if idx < len(keywords) else []
        for i, kw in enumerate(kws):
            st.checkbox(f"✓ {kw}", key=f"kw_{idx}_{i}")

    st.markdown("---")

    rating_key = f"rating_{idx}"
    selected = st.radio(
        "How satisfied are you with this question's relevance?",
        options=LIKERT_OPTIONS,
        key=rating_key,
        index=None,
        horizontal=True,
    )

    st.markdown("")
    col1, _ = st.columns([1, 5])
    with col1:
        label = "Finish" if idx == total - 1 else "Next →"
        if st.button(label, disabled=selected is None):
            score = LIKERT_OPTIONS.index(selected) + 1
            checked_kws = [
                kws[i]
                for i in range(len(kws))
                if st.session_state.get(f"kw_{idx}_{i}", False)
            ]
            st.session_state.answers.append({
                "question": questions[idx],
                "keywords": kws,
                "checked_keywords": checked_kws,
                "rating": score,
            })
            st.session_state.q_index += 1
            if st.session_state.q_index >= total:
                st.session_state.done = True
            st.rerun()


def render_summary():
    st.success("Interview complete!")
    st.markdown("### Your responses")

    for i, item in enumerate(st.session_state.answers, 1):
        with st.container(border=True):
            st.markdown(f"**Q{i}.** {item['question']}")
            c1, c2 = st.columns([1, 1])
            with c1:
                st.markdown(f"**Rating:** {item['rating']} / 5")
            with c2:
                st.markdown("**Expected Keywords**")
                checked = set(item.get("checked_keywords", []))
                for kw in item.get("keywords", []):
                    icon = "✅" if kw in checked else "⬜"
                    st.markdown(f"{icon} {kw}")

    st.markdown("")
    if st.button("← Back to all listings"):
        go_home()
        st.rerun()


def main():
    st.set_page_config(page_title="MONA AI — Interview Support", page_icon="🤖", layout="centered")
    init_state()

    api_key = get_api_key()
    if not api_key:
        st.error(
            "No Gemini API key found. Set `GEMINI_API_KEY` in your `.env` file."
        )
        st.stop()

    if st.session_state.page == "home":
        render_home()
    else:
        render_detail(api_key)


if __name__ == "__main__":
    main()
