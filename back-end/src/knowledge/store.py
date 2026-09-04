from pathlib import Path

from langchain_chroma import Chroma

from knowledge.embeddings import embeddings

# Persist under back-end/data/ so runtime DB files stay out of src/ and git.
_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma_db"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

vector_store = Chroma(
    collection_name="knowledge",
    embedding_function=embeddings,
    persist_directory=str(_DATA_DIR),
)
