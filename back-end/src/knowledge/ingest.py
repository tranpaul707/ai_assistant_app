from knowledge.chunking import chunk_text
from knowledge.store import vector_store


def ingest(documents, filename: str, *, source_type: str | None = None):
    """Chunk documents and upsert into Chroma, one copy per filename.

    Uploaded files are tagged with the real filename in metadata and content
    (``<source: Resume.pdf>``) so retrieval can cite the originating file.
    """
    inferred = source_type or (
        "email" if str(filename).startswith("email:") else "upload"
    )
    chunks = chunk_text(documents)
    for chunk in chunks:
        chunk.metadata["source"] = filename
        chunk.metadata["source_type"] = chunk.metadata.get("source_type") or inferred
        if inferred == "upload":
            chunk.metadata["filename"] = filename
            tag = f"<source: {filename}>"
            content = chunk.page_content or ""
            if not content.lstrip().startswith("<source:"):
                chunk.page_content = f"{tag}\n\n{content}".strip()

    existing = vector_store.get(where={"source": filename})
    if existing["ids"]:
        vector_store.delete(ids=existing["ids"])

    ids = [f"{filename}-{i}" for i in range(len(chunks))]
    vector_store.add_documents(documents=chunks, ids=ids)
