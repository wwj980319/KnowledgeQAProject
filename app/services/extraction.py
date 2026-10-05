import io

from pypdf import PdfReader

ALLOWED_EXTENSIONS = {".txt", ".pdf"}


def extract_text(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError(f"Unsupported file type: {filename}")
