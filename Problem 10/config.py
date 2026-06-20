import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

VIRUSTOTAL_API_KEY = os.getenv("VIRUSTOTAL_API_KEY", "")

IMAP_HOST = os.getenv("IMAP_HOST", "")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASS = os.getenv("IMAP_PASS", "")

CRIMINAL_RECORD_EXPIRY_DAYS = int(os.getenv("CRIMINAL_RECORD_EXPIRY_DAYS", 90))

DB_PATH = os.getenv("DB_PATH", "applications.db")
