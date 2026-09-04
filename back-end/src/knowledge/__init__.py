"""Knowledge / RAG data plane: load → chunk → ingest → retrieve.

Agent tools and HTTP routes should call into this package rather than
talking to Chroma or file loaders directly. That keeps a clear boundary
for future external sources (e.g. Outlook ingestion) without mixing
auth/credentials into LangGraph state.
"""
