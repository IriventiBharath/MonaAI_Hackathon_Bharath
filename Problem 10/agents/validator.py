"""Agent 5: Validation — checks document completeness and date validity."""
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from agents.classifier import DocumentType
from agents.extractor import ExtractionResult
from config import CRIMINAL_RECORD_EXPIRY_DAYS


@dataclass
class ValidationReport:
    cv_present: bool = False
    permit_present: bool = False
    criminal_record_present: bool = False
    permit_expiry: str | None = None
    permit_valid: bool | None = None
    criminal_record_issue_date: str | None = None
    criminal_record_valid: bool | None = None
    overall_valid: bool = False
    notes: list[str] = field(default_factory=list)
    extracted_data: dict = field(default_factory=dict)

    def as_db_record(self) -> dict:
        return {
            "cv_present": self.cv_present,
            "permit_present": self.permit_present,
            "criminal_record_present": self.criminal_record_present,
            "permit_expiry": self.permit_expiry,
            "permit_valid": self.permit_valid,
            "criminal_record_issue_date": self.criminal_record_issue_date,
            "criminal_record_valid": self.criminal_record_valid,
            "overall_valid": self.overall_valid,
            "extracted_data": json.dumps(self.extracted_data),
            "notes": "; ".join(self.notes),
        }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def validate(results: list[ExtractionResult],
             expiry_days: int = CRIMINAL_RECORD_EXPIRY_DAYS) -> ValidationReport:
    report = ValidationReport()
    today = date.today()

    for result in results:
        doc_type = result.doc_type
        data = result.data
        report.extracted_data[result.filename] = {"type": doc_type, "data": data}

        if doc_type == DocumentType.CV:
            report.cv_present = True
            report.notes.append("CV: present")

        elif doc_type in (DocumentType.WORK_PERMIT, DocumentType.RESIDENCE_PERMIT):
            report.permit_present = True
            expiry_str = data.get("expiry_date")
            report.permit_expiry = expiry_str
            expiry_date = _parse_date(expiry_str)
            if expiry_date is None:
                report.permit_valid = False
                report.notes.append(f"{doc_type}: expiry date not found or unparseable")
            elif expiry_date > today:
                report.permit_valid = True
                report.notes.append(f"{doc_type}: valid until {expiry_date}")
            else:
                report.permit_valid = False
                report.notes.append(f"{doc_type}: EXPIRED on {expiry_date}")

        elif doc_type == DocumentType.CRIMINAL_RECORD:
            report.criminal_record_present = True
            issue_str = data.get("issue_date")
            report.criminal_record_issue_date = issue_str
            issue_date = _parse_date(issue_str)
            cutoff = today - timedelta(days=expiry_days)
            if issue_date is None:
                report.criminal_record_valid = False
                report.notes.append("Criminal record: issue date not found or unparseable")
            elif issue_date >= cutoff:
                report.criminal_record_valid = True
                report.notes.append(f"Criminal record: issued {issue_date}, within {expiry_days}-day window")
            else:
                report.criminal_record_valid = False
                report.notes.append(f"Criminal record: EXPIRED (issued {issue_date}, cutoff {cutoff})")

    # Missing document notes
    if not report.cv_present:
        report.notes.append("CV: MISSING")
    if not report.permit_present:
        report.notes.append("Permit: MISSING")
    if not report.criminal_record_present:
        report.notes.append("Criminal record: MISSING")

    report.overall_valid = (
        report.cv_present
        and report.permit_present
        and report.criminal_record_present
        and report.permit_valid is True
        and report.criminal_record_valid is True
    )

    return report
