"""Tests for email ingest dedupe keying."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from langchain_core.documents import Document


def test_ingest_uses_source_key_and_replaces():
    docs = [Document(page_content="hello world " * 20, metadata={"email_id": "e1"})]
    store = MagicMock()
    store.get.return_value = {"ids": ["email:e1-0"]}
    chunks = [
        Document(page_content="chunk-a", metadata={}),
        Document(page_content="chunk-b", metadata={}),
    ]

    with (
        patch("knowledge.ingest.vector_store", store),
        patch("knowledge.ingest.chunk_text", return_value=chunks),
    ):
        from knowledge.ingest import ingest

        ingest(docs, "email:e1")

    store.delete.assert_called_once_with(ids=["email:e1-0"])
    store.add_documents.assert_called_once()
    kwargs = store.add_documents.call_args.kwargs
    assert kwargs["ids"] == ["email:e1-0", "email:e1-1"]
    assert all(c.metadata.get("source") == "email:e1" for c in kwargs["documents"])
