from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool

from knowledge.retrieve import retrieve


@tool(
    "search_private_knowledge",
    description=(
        "Search the user's uploaded documents for relevant passages with source "
        "provenance. Use for document questions, or alongside LIVE Gmail tools "
        "for email/document comparisons. Does not search Gmail or archived email."
    ),
    response_format="content",
)
def search_private_knowledge(query: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
    """Search uploaded/stored documents for passages that answer the query.

    Call this ONLY when the user needs facts from the knowledge base documents
    (quotes, plot details, character names, or other content that must come from
    those files). Pass a short, focused search query — not the full chat history.

    Do NOT call this for greetings, chit-chat, general knowledge, coding help,
    opinions, or anything answerable without the documents.
    """

    user_sub = (config.get("configurable") or {}).get("user_sub")
    if not user_sub:
        return "Sign in to search your private documents."
    documents = retrieve(query, user_sub=user_sub)
    if not documents:
        return "No relevant documents were found."

    blocks = []
    for doc in documents:
        filename = (
            (doc.metadata or {}).get("filename") or (doc.metadata or {}).get("source") or "unknown"
        )
        source_type = (doc.metadata or {}).get("source_type") or ""
        header = f"[source: {filename}]" if source_type != "email" else "[source: gmail]"
        blocks.append(f"{header}\n{doc.page_content}")
    return "\n\n".join(blocks)
