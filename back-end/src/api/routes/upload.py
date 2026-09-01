from pathlib import Path
from io import BytesIO
from fastapi import APIRouter, File, UploadFile
import io
from pypdf import PdfReader

router = APIRouter()

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
   data = await file.read()
   buffer = io.BytesIO(data)
   pdf_text = PdfReader(buffer)

   for page in pdf_text.pages:
    print(page.extract_text())



   