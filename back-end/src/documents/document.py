import pathlib
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
)

def load_file(file, file_name: str):

    if file_name.endswith(".txt"):
        loader = TextLoader(file)

    elif file_name.endswith(".pdf"):
        loader = PyPDFLoader(file)

    elif file_name.endswith(".docx"):
        loader = Docx2txtLoader(file)

    else:
        raise ValueError(f"Unsupported file type: {file_name}")

    return loader.load()