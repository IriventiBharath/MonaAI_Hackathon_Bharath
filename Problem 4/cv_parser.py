import json
from pathlib import Path

import fitz  # PyMuPDF


def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages).strip()


def save_json(data: dict, output_dir: Path, stem: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_markdown(data: dict, output_dir: Path, stem: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = []

    name = data.get("name", "Unknown")
    title = data.get("title", "")
    lines.append(f"# {name}" + (f" — {title}" if title else ""))
    lines.append("")

    contact = data.get("contact", {})
    if any(contact.values()):
        lines.append("## Contact")
        for key, val in contact.items():
            if val:
                lines.append(f"- **{key.replace('_', ' ').title()}**: {val}")
        lines.append("")

    summary = data.get("profile_summary", "")
    if summary:
        lines.append("## Profile")
        lines.append(summary)
        lines.append("")

    skills = data.get("skills", [])
    if skills:
        lines.append("## Skills")
        lines.append(", ".join(skills))
        lines.append("")

    experience = data.get("experience", [])
    if experience:
        lines.append("## Experience")
        for job in experience:
            heading = f"### {job.get('title', '')} at {job.get('company', '')}"
            dates = job.get("dates", "")
            if dates:
                heading += f" ({dates})"
            lines.append(heading)
            for bullet in job.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    education = data.get("education", [])
    if education:
        lines.append("## Education")
        for edu in education:
            degree = edu.get("degree", "")
            inst = edu.get("institution", "")
            dates = edu.get("dates", "")
            entry = f"- **{degree}**"
            if inst:
                entry += f" — {inst}"
            if dates:
                entry += f" ({dates})"
            lines.append(entry)
        lines.append("")

    certifications = data.get("certifications", [])
    if certifications:
        lines.append("## Certifications")
        for cert in certifications:
            lines.append(f"- {cert}")
        lines.append("")

    languages = data.get("languages", [])
    if languages:
        lines.append("## Languages")
        for lang in languages:
            lines.append(f"- {lang}")
        lines.append("")

    path = output_dir / f"{stem}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
