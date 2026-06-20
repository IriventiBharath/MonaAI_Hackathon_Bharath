import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from cv_parser import extract_text, save_json, save_markdown
from gemini_client import analyze_certificate, analyze_cv, extract_cv_structure

st.set_page_config(
    page_title="Document Analyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🔍 Document Analyzer")
    st.markdown("---")
    st.markdown(
        """
**CV (PDF)**
1. Gemini extracts structured data
2. GitHub & LinkedIn links checked
3. Credibility scored (0–100%)

**Certificate (JPG / PNG)**
1. Image sent directly to Gemini
2. Visual & content authenticity check
3. Fraud risk scored (0–100)
        """
    )
    st.markdown("---")
    st.caption("Powered by Gemini 2.5 Flash")

    if not os.getenv("GEMINI_API_KEY"):
        st.error("GEMINI_API_KEY missing from .env")


# ── Score helpers ───────────────────────────────────────────────────────────────
def _cv_score_color(score: int) -> str:
    if score <= 30:
        return "green"
    if score <= 60:
        return "orange"
    return "red"


def _cert_score_color(score: int) -> str:
    if score <= 20:
        return "green"
    if score <= 50:
        return "orange"
    return "red"


def _verdict_emoji(verdict: str) -> str:
    return {
        "Credible": "🟢",
        "Slightly Suspicious": "🟡",
        "Suspicious": "🟠",
        "Highly Suspicious": "🔴",
    }.get(verdict, "⚪")


def _risk_emoji(risk_level: str) -> str:
    level = risk_level.lower()
    if "low" in level:
        return "🟢"
    if "medium" in level:
        return "🟠"
    return "🔴"


# ── Main ────────────────────────────────────────────────────────────────────────
st.header("Upload a Document")
uploaded_file = st.file_uploader(
    "Choose a CV (PDF) or Certificate (JPG / PNG)",
    type=["pdf", "jpg", "jpeg", "png"],
    label_visibility="collapsed",
)

if uploaded_file is not None:
    stem = Path(uploaded_file.name).stem
    file_ext = Path(uploaded_file.name).suffix.lower()
    is_image = file_ext in (".jpg", ".jpeg", ".png")

    # ── CERTIFICATE PATH ────────────────────────────────────────────────────────
    if is_image:
        st.subheader("Certificate Analysis")

        col_img, col_results = st.columns([1, 2], gap="large")

        with col_img:
            st.image(uploaded_file, caption=uploaded_file.name, use_container_width=True)

        with col_results:
            with st.status("Analyzing certificate...", expanded=True) as status:
                st.write("🧠 Sending image to Gemini for analysis…")
                image_bytes = uploaded_file.getvalue()
                result = analyze_certificate(image_bytes)
                status.update(label="Analysis complete!", state="complete", expanded=False)

            st.markdown("---")

            risk_score = result.get("risk_score", -1)
            risk_level = result.get("risk_level", "Unknown")
            doc_type = result.get("document_type", "Unknown")
            reasoning = result.get("reasoning", "")
            flags = result.get("flags", [])
            extracted = result.get("extracted_information", {})

            # Score
            if risk_score == -1:
                st.warning("Score unavailable (analysis error)")
            else:
                color = _cert_score_color(risk_score)
                st.markdown(
                    f"<h1 style='color:{color}; margin:0'>Risk Score: {risk_score}</h1>",
                    unsafe_allow_html=True,
                )
                st.progress(risk_score / 100)
                emoji = _risk_emoji(risk_level)
                st.markdown(f"### {emoji} {risk_level}")

            st.markdown(f"**Document Type:** {doc_type}")

            if reasoning:
                st.markdown("---")
                st.markdown(f"*{reasoning}*")

            st.markdown("---")
            tab_flags, tab_info = st.tabs(["🚩 Flags", "📋 Extracted Info"])

            with tab_flags:
                if flags:
                    for flag in flags:
                        st.markdown(f"- {flag}")
                else:
                    st.info("No flags identified.")

            with tab_info:
                if extracted:
                    st.json(extracted)
                else:
                    st.info("No structured information extracted.")

            st.markdown("---")
            st.download_button(
                label="⬇ Download Analysis (JSON)",
                data=json.dumps(result, indent=2, ensure_ascii=False),
                file_name=f"{stem}_certificate_analysis.json",
                mime="application/json",
            )

    # ── CV PATH ─────────────────────────────────────────────────────────────────
    else:
        # Save upload to a temp file so PyMuPDF can open it
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        try:
            with st.status("Analyzing CV...", expanded=True) as status:
                st.write("📄 Extracting text from PDF…")
                raw_text = extract_text(tmp_path)

                if not raw_text.strip():
                    status.update(label="Failed", state="error")
                    st.error(
                        "Could not extract text from this PDF. "
                        "It may be a scanned/image-only file."
                    )
                    st.stop()

                st.write("🧠 Structuring CV data with Gemini…")
                cv_data = extract_cv_structure(raw_text)

                st.write("🔗 Checking links and scoring credibility…")
                analysis = analyze_cv(cv_data)

                output_dir = Path("parsed_cvs")
                save_json({**cv_data, "analysis": analysis}, output_dir, stem)
                save_markdown(cv_data, output_dir, stem)

                status.update(label="Analysis complete!", state="complete", expanded=False)

            st.markdown("---")

            score = analysis.get("bullshit_score", -1)
            verdict = analysis.get("verdict", "Unknown")
            explanation = analysis.get("explanation", "")
            red_flags = analysis.get("red_flags", [])
            positive_signals = analysis.get("positive_signals", [])
            link_results = analysis.get("link_results", {})

            col_score, col_detail = st.columns([1, 2], gap="large")

            with col_score:
                st.subheader("Credibility Score")

                if score == -1:
                    st.warning("Score unavailable (analysis error)")
                else:
                    color = _cv_score_color(score)
                    st.markdown(
                        f"<h1 style='color:{color}; margin:0'>{score}%</h1>",
                        unsafe_allow_html=True,
                    )
                    st.progress(score / 100)
                    emoji = _verdict_emoji(verdict)
                    st.markdown(f"### {emoji} {verdict}")

                if explanation:
                    st.markdown("---")
                    st.markdown(f"*{explanation}*")

            with col_detail:
                st.subheader("Findings")
                tab_red, tab_green, tab_links = st.tabs(
                    ["🚩 Red Flags", "✅ Positive Signals", "🔗 Link Check"]
                )

                with tab_red:
                    if red_flags:
                        for flag in red_flags:
                            st.markdown(f"- {flag}")
                    else:
                        st.info("No red flags identified.")

                with tab_green:
                    if positive_signals:
                        for sig in positive_signals:
                            st.markdown(f"- {sig}")
                    else:
                        st.info("No positive signals identified.")

                with tab_links:
                    if link_results:
                        for url, result in link_results.items():
                            is_ok = result == "functional"
                            if is_ok:
                                st.success(f"✅ [{url}]({url})")
                            else:
                                st.error(f"❌ {url}  —  {result}")
                    else:
                        st.info("No GitHub or LinkedIn links found in this CV.")

            st.markdown("---")

            with st.expander("📋 Parsed CV Data (structured JSON)", expanded=False):
                st.json(cv_data)

            full_output = {**cv_data, "analysis": analysis}
            st.download_button(
                label="⬇ Download Full Analysis (JSON)",
                data=json.dumps(full_output, indent=2, ensure_ascii=False),
                file_name=f"{stem}_analysis.json",
                mime="application/json",
            )
            st.caption(f"Results also saved to `parsed_cvs/{stem}.json` and `parsed_cvs/{stem}.md`")

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
