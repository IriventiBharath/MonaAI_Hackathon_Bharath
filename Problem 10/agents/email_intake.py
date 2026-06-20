"""Agent 1: Email Intake — connects to IMAP and extracts PDF attachments."""
from utils.email_utils import connect, fetch_unread, EmailRecord


def run(host: str, port: int, user: str, password: str,
        limit: int | None = None) -> list[EmailRecord]:
    """
    Connect to the IMAP mailbox and return unread emails that have
    at least one PDF attachment. Emails are marked as read after fetching.
    Pass limit=1 to fetch only the most recent unread email.
    """
    conn = connect(host, port, user, password)
    records = fetch_unread(conn, limit=limit)
    conn.logout()

    # Only return emails that actually have PDF attachments
    return [r for r in records if r.attachments]
