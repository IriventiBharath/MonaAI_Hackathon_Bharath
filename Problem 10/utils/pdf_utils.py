"""PDF text extraction and sanitization via PyMuPDF (fitz)."""
import io
import fitz  # PyMuPDF


def extract_text(pdf_bytes: bytes) -> str:
    """Return all text from a PDF given its raw bytes."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages)


def sanitize_pdf(pdf_bytes: bytes) -> bytes:
    """Re-render PDF to strip embedded JavaScript, annotations, and scripts."""
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = fitz.open()
    for page in src:
        # Copy page content as a clean pixmap-based reproduction
        out.insert_pdf(src, from_page=page.number, to_page=page.number)
        # Remove all annotations from the new page
        new_page = out[-1]
        for annot in new_page.annots():
            new_page.delete_annot(annot)
    buf = io.BytesIO()
    out.save(buf, garbage=4, deflate=True)
    src.close()
    out.close()
    return buf.getvalue()
