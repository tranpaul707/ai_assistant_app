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

        ingest(docs, "email:e1", user_sub="owner-a")

    scope = {"$and": [{"user_sub": "owner-a"}, {"source_id": "email:e1"}, {"source_type": "email"}]}
    store.get.assert_called_once_with(where=scope)
    store.delete.assert_called_once_with(where=scope)
    store.add_documents.assert_called_once()
    kwargs = store.add_documents.call_args.kwargs
    assert len(set(kwargs["ids"])) == 2
    assert all(value.startswith("v2:") for value in kwargs["ids"])
    assert all(c.metadata["user_sub"] == "owner-a" for c in kwargs["documents"])
    assert all(c.metadata.get("source") == "email:e1" for c in kwargs["documents"])


def test_ingest_upload_tags_filename_in_metadata_and_content():
    docs = [Document(page_content="resume text here", metadata={})]
    store = MagicMock()
    store.get.return_value = {"ids": []}
    chunks = [Document(page_content="resume text here", metadata={})]

    with (
        patch("knowledge.ingest.vector_store", store),
        patch("knowledge.ingest.chunk_text", return_value=chunks),
    ):
        from knowledge.ingest import ingest

        ingest(docs, "Paul Tran Resume.pdf", source_type="upload", user_sub="owner-a")

    saved = store.add_documents.call_args.kwargs["documents"]
    assert saved[0].metadata["filename"] == "Paul Tran Resume.pdf"
    assert saved[0].metadata["source_type"] == "upload"
    assert saved[0].metadata["source"] == "Paul Tran Resume.pdf"
    assert saved[0].page_content.startswith("<source: Paul Tran Resume.pdf>")


def test_live_gmail_search_neither_imports_nor_calls_chroma():
    """Prove live tools import and execute while every knowledge import is blocked."""
    import subprocess

    script = """
import sys
from importlib.abc import MetaPathFinder
from unittest.mock import patch

class NoKnowledge(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "knowledge" or fullname.startswith("knowledge."):
            raise AssertionError("Live Gmail imported Chroma/embeddings")

sys.meta_path.insert(0, NoKnowledge())
from tools.gmail import search_gmail
from services.gmail.models import EmailSummary, SearchPage
with patch("tools.gmail.client.search_emails", return_value=SearchPage(messages=[
    EmailSummary(id="m1", thread_id="t1", sender="a@example.com", subject="Interview")
])):
    result = search_gmail.invoke({"question": "interview", "keywords": "interview"},
        config={"configurable": {"user_sub": "synthetic-user"}})
assert result["status"] == "ok"
assert "body" not in result["messages"][0]
assert not any(key == "knowledge" or key.startswith("knowledge.") for key in sys.modules)
"""
    import os

    env = dict(os.environ, PYTHONPATH=str(SRC), PYTHON_DOTENV_DISABLED="1")
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
