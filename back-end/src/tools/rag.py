from langchain_core.tools import tool

from knowledge.retrieve import retrieve


@tool(
    "search_private_knowledge",
    description="Search Vector Database for external knowledge",
    response_format="content",
)
def search_private_knowledge(query: str) -> str:
    """Search uploaded/stored documents for passages that answer the query.

    Call this ONLY when the user needs facts from the knowledge base documents
    (quotes, plot details, character names, or other content that must come from
    those files). Pass a short, focused search query — not the full chat history.

    Do NOT call this for greetings, chit-chat, general knowledge, coding help,
    opinions, or anything answerable without the documents.
    """

    documents = retrieve(query)
    if not documents:
        return "No relevant documents were found."

    blocks = []
    for doc in documents:
        filename = (
            (doc.metadata or {}).get("filename")
            or (doc.metadata or {}).get("source")
            or "unknown"
        )
        source_type = (doc.metadata or {}).get("source_type") or ""
        header = f"[source: {filename}]" if source_type != "email" else "[source: gmail]"
        blocks.append(f"{header}\n{doc.page_content}")
    return "\n\n".join(blocks)
