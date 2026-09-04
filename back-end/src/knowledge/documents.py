from pathlib import Path

from langchain_community.document_loaders import (
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)

# Shared with the upload route for validation.
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def load_file(file_path: str, file_name: str):
    """Load a document from a path on disk into LangChain Documents.

    LangChain loaders require a filesystem path (not UploadFile / bytes).
    `file_name` is used only to pick the loader from the extension.
    """
    extension = Path(file_name).suffix.lower()

    if extension == ".txt":
        loader = TextLoader(file_path)
    elif extension == ".pdf":
        loader = PyPDFLoader(file_path)
    elif extension == ".docx":
        loader = Docx2txtLoader(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_name}")

    return loader.load()
