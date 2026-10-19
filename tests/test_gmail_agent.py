"""Exercise the real agent/tool graph with a deterministic model, never a mailbox."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

SRC = Path(__file__).resolve().parents[1] / "back-end" / "src"
sys.path.insert(0, str(SRC))

from services.gmail.models import Email, EmailSummary, SearchPage


class SelectionModel(BaseChatModel):
    """Scripted reasoning steps validate integration, not real model intelligence."""

    @property
    def _llm_type(self):
        return "synthetic-selection"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, HumanMessage):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_gmail",
                        "args": {
                            "question": "latest internship response",
                            "raw_query": "internship OR interview",
                        },
                        "id": "search1",
                    }
                ],
            )
        elif isinstance(last, ToolMessage) and last.name == "search_gmail":
            data = json.loads(last.content)
            candidates = data["messages"]
            chosen = next(
                email for email in candidates if email["subject"] == "Interview invitation"
            )
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_email",
                        "args": {"message_id": chosen["id"]},
                        "id": "read1",
                    }
                ],
            )
        elif isinstance(last, ToolMessage) and last.name == "read_email":
            data = json.loads(last.content)
            response = AIMessage(content=data["message"]["body"])
        else:
            raise AssertionError("Unexpected agent step")
        return ChatResult(generations=[ChatGeneration(message=response)])


def test_agent_searches_metadata_then_reads_only_selected_id_with_injected_user():
    from agents.agent import create_private_agent
    from services.gmail import client

    candidates = SearchPage(
        messages=[
            EmailSummary(
                id="promotion",
                thread_id="tp",
                sender="Offers",
                subject="Internship newsletter",
                preview="Generic course discount",
                labels=["CATEGORY_PROMOTIONS"],
            ),
            EmailSummary(
                id="relevant",
                thread_id="tr",
                sender="Recruiter",
                subject="Interview invitation",
                preview="Your interview is on Friday",
            ),
        ]
    )
    with (
        patch("agents.agent.llm", SelectionModel()),
        patch.object(client, "search_emails", return_value=candidates) as search,
        patch.object(
            client,
            "read_email",
            return_value=Email(
                id="relevant",
                thread_id="tr",
                subject="Interview invitation",
                sender="Recruiter",
                body="Your interview is on Friday.",
            ),
        ) as read,
        patch.object(client, "read_email_thread") as thread,
    ):
        result = create_private_agent().invoke(
            {"messages": [HumanMessage("Summarize my latest internship response")]},
            config={"configurable": {"user_sub": "synthetic-user"}, "recursion_limit": 128},
        )
    assert result["messages"][-1].content == "Your interview is on Friday."
    assert search.call_args.args[0] == "synthetic-user"
    read.assert_called_once_with("synthetic-user", "relevant")
    thread.assert_not_called()
    evidence = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert [message.name for message in evidence] == ["search_gmail", "read_email"]
    assert "body" not in json.loads(evidence[0].content)["messages"][0]
    assert json.loads(evidence[0].content)["messages"][1]["thread_id"] == "tr"


class LoopingReadModel(SelectionModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, ToolMessage) and "limit" in last.content.casefold():
            response = AIMessage(content="Stopped at the retrieval limit.")
        else:
            response = AIMessage(content="", tool_calls=[{
                "name": "read_email", "args": {"message_id": "relevant"}, "id": f"read{len(messages)}",
            }])
        return ChatResult(generations=[ChatGeneration(message=response)])


def test_agent_blocks_reads_after_run_budget():
    from agents.agent import create_private_agent
    from services.gmail import client

    with patch("agents.agent.llm", LoopingReadModel()), patch.object(client, "read_email", return_value=Email(id="relevant", thread_id="tr", sender="Recruiter", subject="Interview", body="Body")) as read:
        result = create_private_agent().invoke(
            {"messages": [HumanMessage("Read the email repeatedly")]},
            config={"configurable": {"user_sub": "synthetic-user"}, "recursion_limit": 128},
        )
    assert read.call_count == 10
    assert "Stopped" in result["messages"][-1].content


class EvaluationModel(SelectionModel):
    """Script all seven retrieval scenarios to check evaluation instrumentation."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        question = next(message.content for message in messages if isinstance(message, HumanMessage) and "Include exact" in message.content)
        last = messages[-1]
        calls = []
        if isinstance(last, HumanMessage):
            if "last five messages" in question:
                calls = [{"name": "read_email_thread", "args": {"thread_id": "conversation", "max_messages": 5}, "id": "thread"}]
            else:
                args = {"question": question, "keywords": "application interview AWS research"}
                if "John" in question:
                    args.update(sender="John", time_range="last_week")
                if "UConn" in question:
                    args.update(sender="UConn", time_range="yesterday")
                calls = [{"name": "search_gmail", "args": args, "id": "search"}]
        elif isinstance(last, ToolMessage) and last.name == "search_gmail":
            candidates = json.loads(last.content)["messages"]
            ids = [email["id"] for email in candidates if email["id"] not in ("newsletter", "aws-old", "job6")]
            calls = [{"name": "read_email", "args": {"message_id": message_id}, "id": message_id} for message_id in ids]
        elif "Compare" in question and not any(isinstance(message, ToolMessage) and message.name == "search_private_knowledge" for message in messages):
            calls = [{"name": "search_private_knowledge", "args": {"query": "study participants"}, "id": "document"}]
        if calls:
            response = AIMessage(content="", tool_calls=calls)
        else:
            evidence = []
            for message in messages:
                if not isinstance(message, ToolMessage):
                    continue
                if message.name == "read_email":
                    evidence.append(json.loads(message.content)["message"]["body"])
                elif message.name == "read_email_thread":
                    evidence.extend(email["body"] for email in json.loads(message.content)["messages"])
                elif message.name == "search_private_knowledge":
                    evidence.append(message.content)
            response = AIMessage(content="\n".join(evidence))
        return ChatResult(generations=[ChatGeneration(message=response)])


def test_synthetic_evaluation_records_selection_grounding_and_read_counts():
    from scripts.evaluate_ai import evaluate_gmail

    results = []

    def run_case(name, operation, expected, matches):
        actual = operation()
        results.append((name, actual, matches(actual)))

    evaluate_gmail(EvaluationModel(), run_case)
    assert len(results) == 7
    assert all(passed for _, _, passed in results)
    assert results[1][1]["full_read_count"] == 5
    assert results[5][1]["thread_counts"] == [5]
    assert results[6][1]["document_calls"] == 1
