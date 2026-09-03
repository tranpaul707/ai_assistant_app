from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from documents.document import load_file

from ingestion.ingest_file import ingest
router = APIRouter()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    safe_name = Path(file.filename).name
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(await file.read())

    documents = load_file(str(dest), safe_name)

    ingest(documents, safe_name)