from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from knowledge.documents import SUPPORTED_EXTENSIONS, load_file
from knowledge.ingest import ingest

router = APIRouter()

# Uploads live under back-end/data/uploads (gitignored), not inside src/.
UPLOAD_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    safe_name = Path(file.filename).name
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {extension}",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(await file.read())

    documents = load_file(str(dest), safe_name)
    ingest(documents, safe_name)
