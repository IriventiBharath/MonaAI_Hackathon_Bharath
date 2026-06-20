"""IMAP helpers: connect, fetch unread messages, extract PDF attachments."""
import imaplib
import email
from email.message import Message
from dataclasses import dataclass, field


@dataclass
class EmailRecord:
    sender: str
    subject: str
    received_at: str
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    # each tuple: (filename, raw_bytes)


def connect(host: str, port: int, user: str, password: str) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(user, password)
    return conn


def fetch_unread(conn: imaplib.IMAP4_SSL, mailbox: str = "INBOX",
                 limit: int | None = None) -> list[EmailRecord]:
    conn.select(mailbox)
    _, data = conn.search(None, "UNSEEN")
    uids = data[0].split()
    # UIDs are oldest-first; take the most recent N
    if limit is not None:
        uids = uids[-limit:]
    records: list[EmailRecord] = []

    for uid in uids:
        _, msg_data = conn.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg: Message = email.message_from_bytes(raw)

        sender = msg.get("From", "")
        subject = msg.get("Subject", "")
        received_at = msg.get("Date", "")

        pdfs: list[tuple[str, bytes]] = []
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = part.get("Content-Disposition", "")
            filename = part.get_filename() or ""

            is_pdf_attachment = (
                content_type == "application/pdf"
                or (filename.lower().endswith(".pdf") and "attachment" in disposition)
            )
            if is_pdf_attachment:
                payload = part.get_payload(decode=True)
                if payload:
                    pdfs.append((filename, payload))

        records.append(EmailRecord(
            sender=sender,
            subject=subject,
            received_at=received_at,
            attachments=pdfs,
        ))

        # Mark as read
        conn.store(uid, "+FLAGS", "\\Seen")

    return records
