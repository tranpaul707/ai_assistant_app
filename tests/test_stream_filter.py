"""Tests for filtering leaked tool-call JSON from assistant streams."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from agents.agent import is_answer_token, looks_like_tool_args_json, message_text
from langchain_core.messages import AIMessageChunk


def test_looks_like_tool_args_json_detects_gmail_args():
    payload = """{
  "keywords": "content",
  "sender": "",
  "to": "",
  "subject": "",
  "raw_query": ""
}"""
    assert looks_like_tool_args_json(payload)
    assert looks_like_tool_args_json('{"keywords": "internship", "sender": ""}')
    assert not looks_like_tool_args_json("Here is what I found in your email.")
    assert not looks_like_tool_args_json('{"foo": 1, "bar": 2}')


def test_is_answer_token_rejects_tool_json_content():
    bad = AIMessageChunk(
        content='{"keywords": "content", "sender": "", "to": "", "subject": "", "raw_query": ""}'
    )
    good = AIMessageChunk(content="You received an internship offer from HR.")
    toolish = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"index": 0, "id": "1", "name": "search_gmail", "args": "{}", "type": "tool_call_chunk"}
        ],
    )
    assert not is_answer_token(bad)
    assert is_answer_token(good)
    assert not is_answer_token(toolish)


def test_message_text_joins_blocks():
    assert message_text([{"type": "text", "text": "Hello"}, {"type": "text", "text": " world"}]) == (
        "Hello world"
    )
