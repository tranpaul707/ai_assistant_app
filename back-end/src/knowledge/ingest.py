from hashlib import sha256

from chromadb.api.types import Where

from core.identity import owner_namespace, require_identity
from knowledge.chunking import chunk_text
from knowledge.store import vector_store


def ingest(
    documents,
    filename: str,
    *,
    user_sub: str,
    source_type: str | None = None,
    source_id: str | None = None,
):
    """Chunk and replace one owner's resource; overwrite untrusted owner metadata.

    Uploaded files are tagged with the real filename in metadata and content
    (``<source: Resume.pdf>``) so retrieval can cite the originating file.
    """
    require_identity(user_sub)
    inferred = source_type or ("email" if str(filename).startswith("email:") else "upload")
    if inferred not in {"email", "upload"}:
        raise ValueError("Unknown source type")
    resource = source_id or filename
    if not isinstance(resource, str) or not resource:
        raise ValueError("A source ID is required")
    scope: Where = {
        "$and": [{"user_sub": user_sub}, {"source_id": resource}, {"source_type": inferred}]
    }
    chunks = chunk_text(documents)
    for chunk in chunks:
        chunk.metadata["source"] = filename
        chunk.metadata["user_sub"] = user_sub
        chunk.metadata["source_id"] = resource
        chunk.metadata["source_type"] = inferred
        if inferred == "upload":
            chunk.metadata["filename"] = filename
            tag = f"<source: {filename}>"
            content = chunk.page_content or ""
            if not content.lstrip().startswith("<source:"):
                chunk.page_content = f"{tag}\n\n{content}".strip()

    existing = vector_store.get(where=scope)
    if existing["ids"]:
        vector_store.delete(where=scope)

    resource_hash = sha256(f"{inferred}\0{resource}".encode()).hexdigest()
    ids = [f"v2:{owner_namespace(user_sub)}:{resource_hash}:{i}" for i in range(len(chunks))]
    vector_store.add_documents(documents=chunks, ids=ids)
