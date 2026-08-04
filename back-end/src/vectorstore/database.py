from langchain_chroma import Chroma
from embedding.embedder import embeddings

vector_store = Chroma(
    collection_name="knowledge",
    embedding_function=embeddings,
    persist_directory="chroma_db",
)

