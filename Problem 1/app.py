import imaplib
import email
import os
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from agent import classify_invoice

load_dotenv()

IMAP_HOST = os.environ["IMAP_HOST"]
IMAP_PORT = int(os.environ["IMAP_PORT"])
IMAP_USER = os.environ["IMAP_USER"]
IMAP_PASS = os.environ["IMAP_PASS"]

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".docx"}

DEPT_COLORS = {
    "Facilities":        "#e67e22",
    "IT":                "#2980b9",
    "Administration":    "#27ae60",
    "Finance":           "#8e44ad",
    "Travel & Expenses": "#c0392b",
}


def fetch_latest_invoice_email() -> dict | None:
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(IMAP_USER, IMAP_PASS)
    mail.select("INBOX")

    _, messages = mail.search(None, "ALL")
    email_ids = messages[0].split()

    for eid in reversed(email_ids):
        _, data = mail.fetch(eid, "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)

        for part in msg.walk():
            if "attachment" not in part.get("Content-Disposition", ""):
                continue
            filename = part.get_filename()
            if not filename:
                continue
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            payload = part.get_payload(decode=True)
            mail.logout()
            return {
                "subject": msg.get("Subject", "(no subject)"),
                "from_":   msg.get("From", ""),
                "date":    msg.get("Date", ""),
                "filename": filename,
                "ext":      ext,
                "data":     payload,
            }

    mail.logout()
    return None


st.set_page_config(page_title="Invoice Email Classifier", page_icon="📧", layout="centered")
st.title("📧 Invoice Email Classifier")
st.caption("Reads the latest email with an invoice attachment and routes it to the right department.")

if st.button("Fetch & Classify Latest Email", type="primary", use_container_width=True):
    with st.spinner("Connecting to inbox..."):
        email_data = fetch_latest_invoice_email()

    if email_data is None:
        st.error("No email with a supported attachment (PDF / PNG / DOCX) found in your inbox.")
        st.stop()

    st.subheader("Email Details")
    col1, col2 = st.columns(2)
    col1.markdown(f"**From:** {email_data['from_']}")
    col1.markdown(f"**Subject:** {email_data['subject']}")
    col2.markdown(f"**Date:** {email_data['date']}")
    col2.markdown(f"**Attachment:** `{email_data['filename']}`")

    st.divider()

    with st.spinner("Classifying invoice with Gemini..."):
        with tempfile.NamedTemporaryFile(
            suffix=email_data["ext"], delete=False
        ) as tmp:
            tmp.write(email_data["data"])
            tmp_path = Path(tmp.name)

        try:
            result = classify_invoice(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    category   = result["predicted_category"]
    department = result["department"]
    dept_color = DEPT_COLORS.get(department, "#555555")

    st.subheader("Classification Result")

    r1, r2 = st.columns(2)
    with r1:
        st.metric("Invoice Category", category)
    with r2:
        st.markdown(
            f"<div style='background:{dept_color};color:white;padding:12px 18px;"
            f"border-radius:8px;text-align:center;font-size:1.1rem;font-weight:600;"
            f"margin-top:4px'>Route to: {department}</div>",
            unsafe_allow_html=True,
        )
