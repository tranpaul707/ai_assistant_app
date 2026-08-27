from pathlib import Path

from fastapi import APIRouter, File, UploadFile

router = APIRouter()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    print("Request Received")