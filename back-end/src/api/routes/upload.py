from pathlib import Path

from fastapi import APIRouter, File, UploadFile

router = APIRouter()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = UPLOAD_DIR / file.filename
    contents = await file.read()
    file_path.write_bytes(contents)

    return {"filename": file.filename, "message": "File uploaded successfully"}
