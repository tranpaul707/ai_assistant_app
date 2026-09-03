from chunking.textsplitter import chunk_text
from vectorstore.database import vector_store


def ingest(documents, filename: str):
    """Ingests uploaded file into the vector database for future RAG usage."""
    chunks = chunk_text(documents)
    for chunk in chunks:
        chunk.metadata["source"] = filename

    existing = vector_store.get(where={"source": filename})
    if existing["ids"]:
        vector_store.delete(ids=existing["ids"])

    ids = [f"{filename}-{i}" for i in range(len(chunks))]
    vector_store.add_documents(documents=chunks, ids=ids)
