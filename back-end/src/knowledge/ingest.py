from knowledge.chunking import chunk_text
from knowledge.store import vector_store


def ingest(documents, filename: str):
    """Chunk documents and upsert into Chroma, one copy per filename."""
    chunks = chunk_text(documents)
    for chunk in chunks:
        chunk.metadata["source"] = filename

    existing = vector_store.get(where={"source": filename})
    if existing["ids"]:
        vector_store.delete(ids=existing["ids"])

    ids = [f"{filename}-{i}" for i in range(len(chunks))]
    vector_store.add_documents(documents=chunks, ids=ids)
