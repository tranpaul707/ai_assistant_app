from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from core.auth import AuthenticatedUser
from core.identity import owner_namespace
from knowledge.documents import SUPPORTED_EXTENSIONS, load_file
from knowledge.ingest import ingest

router = APIRouter()

# Uploads live under back-end/data/uploads (gitignored), not inside src/.
UPLOAD_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"


@router.post("/upload")
async def upload_file(user_sub: AuthenticatedUser, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    safe_name = Path(file.filename).name
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {extension}",
        )

    owner_dir = UPLOAD_DIR / "v2" / owner_namespace(user_sub)
    owner_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    document_id = str(uuid4())
    dest = owner_dir / f"{document_id}{extension}"
    contents = await file.read()
    with dest.open("xb") as handle:
        dest.chmod(0o600)
        handle.write(contents)

    documents = load_file(str(dest), safe_name)
    for document in documents:
        document.metadata["filename"] = safe_name
        document.metadata["source_type"] = "upload"
    ingest(documents, safe_name, user_sub=user_sub, source_type="upload", source_id=document_id)
    return {
        "status": "ok",
        "filename": safe_name,
        "document_id": document_id,
        "chunks_ready": True,
    }
