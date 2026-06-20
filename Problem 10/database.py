import sqlite3
from datetime import datetime
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id                        INTEGER PRIMARY KEY AUTOINCREMENT,
                email_sender              TEXT,
                email_subject             TEXT,
                received_at               DATETIME,
                processed_at              DATETIME,
                security_passed           BOOLEAN,
                security_notes            TEXT,
                cv_present                BOOLEAN DEFAULT 0,
                permit_present            BOOLEAN DEFAULT 0,
                criminal_record_present   BOOLEAN DEFAULT 0,
                permit_expiry             DATE,
                permit_valid              BOOLEAN,
                criminal_record_issue_date DATE,
                criminal_record_valid     BOOLEAN,
                overall_valid             BOOLEAN DEFAULT 0,
                extracted_data            TEXT,
                notes                     TEXT
            )
        """)
        conn.commit()


def insert_application(record: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO applications (
                email_sender, email_subject, received_at, processed_at,
                security_passed, security_notes,
                cv_present, permit_present, criminal_record_present,
                permit_expiry, permit_valid,
                criminal_record_issue_date, criminal_record_valid,
                overall_valid, extracted_data, notes
            ) VALUES (
                :email_sender, :email_subject, :received_at, :processed_at,
                :security_passed, :security_notes,
                :cv_present, :permit_present, :criminal_record_present,
                :permit_expiry, :permit_valid,
                :criminal_record_issue_date, :criminal_record_valid,
                :overall_valid, :extracted_data, :notes
            )
        """, record)
        conn.commit()
        return cur.lastrowid


def fetch_all_applications() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY processed_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
