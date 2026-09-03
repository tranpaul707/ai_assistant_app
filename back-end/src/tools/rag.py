from langchain_core.tools import tool

from retrieval.search import retrieve
from ingestion.ingest_file import ingest

@tool("search_private_knowledge", description="Search Vector Database for external knowledge", response_format="content")
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

    return "\n\n".join(doc.page_content for doc in documents)
