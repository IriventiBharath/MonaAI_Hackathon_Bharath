"""Streamlit UI — Document Compliance Multi-Agent System."""
import json
import logging
from datetime import datetime

import streamlit as st

import config
import database
from agents import classifier, extractor, security_agent, validator
from agents.email_intake import run as fetch_emails
from utils.email_utils import EmailRecord

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="Document Compliance System",
    page_icon="🔍",
    layout="wide",
)

# ── Database init ────────────────────────────────────────────────────────────
database.init_db()

# ── Session state defaults ───────────────────────────────────────────────────
if "fetched_emails" not in st.session_state:
    st.session_state.fetched_emails: list[EmailRecord] = []
if "last_fetch" not in st.session_state:
    st.session_state.last_fetch = None
if "processing_log" not in st.session_state:
    st.session_state.processing_log: list[str] = []


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Configuration")

    st.subheader("Google Gemini")
    api_key = st.text_input("Gemini API Key", value=config.GEMINI_API_KEY,
                             type="password", key="api_key")

    st.subheader("VirusTotal")
    vt_key = st.text_input("VirusTotal API Key", value=config.VIRUSTOTAL_API_KEY,
                            type="password", key="vt_key")

    st.subheader("IMAP Settings")
    imap_host = st.text_input("Host", value=config.IMAP_HOST)
    imap_port = st.number_input("Port", value=config.IMAP_PORT, step=1)
    imap_user = st.text_input("Username", value=config.IMAP_USER)
    imap_pass = st.text_input("Password", value=config.IMAP_PASS, type="password")

    st.subheader("Validation Rules")
    expiry_days = st.number_input(
        "Criminal record max age (days)",
        value=config.CRIMINAL_RECORD_EXPIRY_DAYS,
        min_value=1, step=1,
    )

    st.subheader("Fetch Settings")
    fetch_limit = st.number_input(
        "Max emails to fetch (0 = all)",
        min_value=0, value=1, step=1,
    )

    st.divider()
    fetch_btn = st.button("📥 Fetch Unread Emails", use_container_width=True)


# ── Email fetch ───────────────────────────────────────────────────────────────
if fetch_btn:
    if not all([imap_host, imap_user, imap_pass]):
        st.sidebar.error("Please fill in all IMAP fields.")
    else:
        with st.sidebar:
            with st.spinner("Connecting to mailbox…"):
                try:
                    emails = fetch_emails(
                        host=imap_host,
                        port=int(imap_port),
                        user=imap_user,
                        password=imap_pass,
                        limit=int(fetch_limit) if fetch_limit > 0 else None,
                    )
                    st.session_state.fetched_emails = emails
                    st.session_state.last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.success(f"Fetched {len(emails)} email(s) with PDF attachments.")
                except Exception as exc:
                    st.error(f"IMAP error: {exc}")


# ── Main area ────────────────────────────────────────────────────────────────
st.title("🔍 Document Compliance System")
st.caption("Automated vetting pipeline: Email Intake → Security → Classify → Extract → Validate")

if st.session_state.last_fetch:
    st.info(f"Last fetch: {st.session_state.last_fetch} — "
            f"{len(st.session_state.fetched_emails)} email(s) pending processing")

# ── Process button ────────────────────────────────────────────────────────────
if st.session_state.fetched_emails:
    process_btn = st.button("▶️ Process All Emails", type="primary", use_container_width=True)
else:
    process_btn = False
    st.info("Use the sidebar to connect to your mailbox and fetch emails.")


def _status(flag: bool | None) -> str:
    if flag is True:
        return "✅"
    if flag is False:
        return "❌"
    return "➖"


if process_btn:
    log: list[str] = []
    progress = st.progress(0.0, text="Starting pipeline…")
    total = len(st.session_state.fetched_emails)

    for idx, email_record in enumerate(st.session_state.fetched_emails):
        progress.progress((idx) / total, text=f"Processing email {idx + 1}/{total}: {email_record.subject}")
        log.append(f"\n--- Email {idx + 1}: {email_record.subject} from {email_record.sender} ---")

        # Agent 2: Security scan all attachments
        log.append("  [Agent 2] Running security scans…")
        sec_results = security_agent.scan_all(email_record.attachments, gemini_key=api_key, vt_key=vt_key)

        failed_files = [r for r in sec_results if not r.passed]
        if failed_files:
            reasons = "; ".join(f"{r.filename}: {r.reason}" for r in failed_files)
            log.append(f"  [Agent 2] BLOCKED — {reasons}")
            database.insert_application({
                "email_sender": email_record.sender,
                "email_subject": email_record.subject,
                "received_at": email_record.received_at,
                "processed_at": datetime.now().isoformat(),
                "security_passed": False,
                "security_notes": reasons,
                "cv_present": False,
                "permit_present": False,
                "criminal_record_present": False,
                "permit_expiry": None,
                "permit_valid": None,
                "criminal_record_issue_date": None,
                "criminal_record_valid": None,
                "overall_valid": False,
                "extracted_data": "{}",
                "notes": f"Security blocked: {reasons}",
            })
            continue

        log.append("  [Agent 2] Security: PASSED")

        # Build map of filename → clean bytes
        clean_map: dict[str, bytes] = {}
        for sr in sec_results:
            if sr.sanitized_bytes:
                clean_map[sr.filename] = sr.sanitized_bytes
        # Fallback to originals for any that passed without sanitized bytes
        for fname, raw in email_record.attachments:
            if fname not in clean_map:
                clean_map[fname] = raw

        # Agent 3: Classify each document
        log.append("  [Agent 3] Classifying documents…")
        classified: list[tuple[str, bytes, classifier.DocumentType]] = []
        for fname, pdf_bytes in clean_map.items():
            doc_type = classifier.classify(pdf_bytes, api_key=api_key)
            log.append(f"    {fname} → {doc_type}")
            classified.append((fname, pdf_bytes, doc_type))

        # Agent 4: Extract information
        log.append("  [Agent 4] Extracting information…")
        extraction_results: list[extractor.ExtractionResult] = []
        for fname, pdf_bytes, doc_type in classified:
            result = extractor.extract(fname, pdf_bytes, doc_type, api_key=api_key)
            if result.error:
                log.append(f"    {fname}: extraction error — {result.error}")
            else:
                log.append(f"    {fname}: extracted {list(result.data.keys())}")
            extraction_results.append(result)

        # Agent 5: Validate
        log.append("  [Agent 5] Validating…")
        report = validator.validate(extraction_results, expiry_days=int(expiry_days))
        for note in report.notes:
            log.append(f"    {note}")
        log.append(f"  Overall: {'PASS ✅' if report.overall_valid else 'FAIL ❌'}")

        db_record = report.as_db_record()
        db_record.update({
            "email_sender": email_record.sender,
            "email_subject": email_record.subject,
            "received_at": email_record.received_at,
            "processed_at": datetime.now().isoformat(),
            "security_passed": True,
            "security_notes": "; ".join(r.reason for r in sec_results),
        })
        database.insert_application(db_record)

    progress.progress(1.0, text="Done!")
    st.session_state.processing_log = log
    st.session_state.fetched_emails = []
    st.success("Processing complete. Results saved to database.")

if st.session_state.processing_log:
    with st.expander("Pipeline log", expanded=True):
        st.code("\n".join(st.session_state.processing_log), language=None)

# ── Results table ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("Application Results")

rows = database.fetch_all_applications()
if not rows:
    st.info("No applications processed yet.")
else:
    # Summary table
    table_rows = []
    for r in rows:
        table_rows.append({
            "ID": r["id"],
            "From": r["email_sender"],
            "Subject": r["email_subject"],
            "Received": r["received_at"],
            "Security": _status(r["security_passed"]),
            "CV": _status(r["cv_present"]),
            "Permit": _status(r["permit_present"]),
            "Criminal Record": _status(r["criminal_record_present"]),
            "Permit Valid": _status(r["permit_valid"]),
            "CR Valid": _status(r["criminal_record_valid"]),
            "Overall": _status(r["overall_valid"]),
        })

    st.dataframe(table_rows, use_container_width=True)

    # Detail expandable per row
    st.subheader("Application Details")
    for r in rows:
        label = (
            f"{'✅' if r['overall_valid'] else '❌'} "
            f"#{r['id']} — {r['email_sender']} | {r['email_subject']}"
        )
        with st.expander(label):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Checks**")
                st.write(f"Security passed: {_status(r['security_passed'])}")
                st.write(f"CV present: {_status(r['cv_present'])}")
                st.write(f"Permit present: {_status(r['permit_present'])}")
                st.write(f"Criminal record present: {_status(r['criminal_record_present'])}")
                st.write(f"Permit valid: {_status(r['permit_valid'])} "
                         f"(expires: {r['permit_expiry'] or 'N/A'})")
                st.write(f"Criminal record valid: {_status(r['criminal_record_valid'])} "
                         f"(issued: {r['criminal_record_issue_date'] or 'N/A'})")
            with col2:
                st.markdown("**Notes**")
                st.write(r["notes"] or "—")
                if r["security_notes"]:
                    st.markdown("**Security notes**")
                    st.write(r["security_notes"])
                if r["extracted_data"]:
                    st.markdown("**Extracted data**")
                    try:
                        st.json(json.loads(r["extracted_data"]))
                    except Exception:
                        st.write(r["extracted_data"])
