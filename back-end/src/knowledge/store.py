from pathlib import Path

from langchain_chroma import Chroma

from knowledge.embeddings import embeddings

# Persist under back-end/data/ so runtime DB files stay out of src/ and git.
_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma_db"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

vector_store = Chroma(
    # Legacy shared chunks remain inaccessible until an explicit backed-up migration.
    collection_name="knowledge_private_v2",
    embedding_function=embeddings,
    persist_directory=str(_DATA_DIR),
)
