import pathlib
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
)
import asyncio

def load_file(file):
    file_extension = pathlib.Path(file).suffix

    if file_extension == ".txt":
        loader = PyPDFLoader(file)

    elif file_extension == ".pdf":
        loader = TextLoader(file)

    elif file_extension == ".docx":
        loader = Docx2txtLoader(file)

    else:
        raise ValueError(f"Unsupported file type: {file_extension}")

    return loader.load()