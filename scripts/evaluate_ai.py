"""Small synthetic real-model regression suite; never reads a real Gmail account."""

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_chroma import Chroma
from langchain_core.documents import Document

from agents.agent import SYSTEM_PROMPT
from agents.graph import classify
from knowledge.embeddings import embeddings
from knowledge.ingest import ingest
from knowledge.retrieve import retrieve
from llm.client import llm


def evaluate(results: list[dict]) -> None:
    """Evaluate synthetic fixtures with the application's model and retrieval code."""
    # Use the application model and prompts with bounded output/context for CPU CI.
    model = llm.model_copy(update={"num_predict": 128, "num_ctx": 2048})

    def run_case(name, operation, expected, matches):
        started = time.monotonic()
        try:
            actual = operation()
            passed = bool(matches(actual))
            result = {"name": name, "expected": expected, "actual": actual, "passed": passed}
        except Exception as exc:
            result = {"name": name, "passed": False, "error": type(exc).__name__}
        result["seconds"] = round(time.monotonic() - started, 3)
        results.append(result)
        print(f"{name}: {'PASS' if result['passed'] else 'FAIL'}")

    for query, route in [
        ("What is two plus two?", "general"),
        ("Find emails from Alex about the meeting", "private"),
        ("What does my uploaded project plan say about the launch?", "private"),
    ]:
        with patch("agents.graph.llm", model):
            run_case(
                f"route: {query}", lambda: classify(query), route, lambda value: value == route
            )

    evaluate_gmail(llm.model_copy(update={"num_predict": 512, "num_ctx": 8192}), run_case)

    with TemporaryDirectory(prefix="knowledge-ai-eval-") as directory:
        store = Chroma(
            collection_name="synthetic_evaluation",
            embedding_function=embeddings,
            persist_directory=directory,
        )
        with (
            patch("knowledge.ingest.vector_store", store),
            patch("knowledge.retrieve.vector_store", store),
        ):
            ingest(
                [Document(page_content="Project Aurora launches on November 12, 2027.")],
                "aurora.txt",
                user_sub="synthetic-evaluation",
            )
            ingest(
                [Document(page_content="The cafeteria serves lentil soup on Tuesday.")],
                "cafeteria.txt",
                user_sub="synthetic-evaluation",
            )
            run_case(
                "retrieval: launch source ranks first",
                lambda: retrieve(
                    "When does Project Aurora launch?", user_sub="synthetic-evaluation"
                )[0].metadata["source"],
                "aurora.txt",
                lambda value: value == "aurora.txt",
            )
            context = "\n".join(
                doc.page_content
                for doc in retrieve(
                    "When does Project Aurora launch?", user_sub="synthetic-evaluation"
                )
            )
            run_case(
                "answer: launch date is grounded",
                lambda: str(
                    model.invoke(
                        [
                            ("system", SYSTEM_PROMPT),
                            (
                                "human",
                                f"Use only this context: {context}\nWhen does Aurora launch?",
                            ),
                        ]
                    ).content
                ),
                "November 12, 2027",
                lambda value: "2027" in value and "12" in value and "november" in value.lower(),
            )
    run_case(
        "answer: abstain when context lacks the budget",
        lambda: str(
            model.invoke(
                [
                    ("system", SYSTEM_PROMPT),
                    (
                        "human",
                        "Context: Project Aurora launches in November. "
                        "Use only that context. What is its exact dollar budget? "
                        "If the context does not say, reply exactly UNKNOWN.",
                    ),
                ]
            ).content
        ),
        "UNKNOWN",
        lambda value: value.strip().upper().rstrip(".") == "UNKNOWN",
    )


def evaluate_gmail(model, run_case) -> None:
    """Run the real private agent against synthetic candidates and instrumented APIs.

    These fixtures exercise selection/query planning, not Google's search engine.
    No Gmail credentials, real mailbox or persistent conversation state are used.
    """
    from datetime import datetime, timedelta, timezone
    from langchain_core.messages import AIMessage, HumanMessage
    from agents.agent import create_private_agent, message_text
    from services.gmail.models import Email, EmailSummary, EmailThread, SearchPage
    from services.gmail.query import calendar_window, gmail_timezone

    now = datetime.now(timezone.utc)
    zone = gmail_timezone()

    def mail(message_id, sender, subject, body, *, age=0, labels=None, thread="conversation"):
        return Email(
            id=message_id,
            thread_id=thread,
            sender=sender,
            subject=subject,
            recipients=["user@synthetic.example"],
            received_at=now - timedelta(days=age),
            preview=body[:300],
            body=body,
            labels=labels or [],
        )

    jobs = [
        mail(
            f"job{i}",
            "Recruiter <ats@synthetic.example>",
            "Application response",
            f"Your application to Synthetic Company {i} is moving to an interview. Code JOB{i}.",
            age=i,
        )
        for i in range(1, 7)
    ]
    newsletter = mail(
        "newsletter",
        "Careers newsletter <news@synthetic.example>",
        "Internship tips",
        "Weekly newsletter: general internship advice and training promotions.",
        labels=["CATEGORY_PROMOTIONS"],
    )
    john = mail(
        "john",
        "John Smith <john@synthetic.example>",
        "Interview response",
        "Your interview is confirmed for Friday. Code FRIDAY.",
    )
    uconn = mail(
        "uconn",
        "Research Coordinator <research@uconn.edu>",
        "Research application response",
        "Your research interview is on Tuesday. Code TUESDAY.",
    )
    aws = mail(
        "aws",
        "Cloud team <cloud@synthetic.example>",
        "AWS project update",
        "The AWS migration is complete. Code MIGRATION.",
    )
    recruiter = mail(
        "recruiter",
        "Recruiter <recruiter@synthetic.example>",
        "Interview invitation",
        "Your interview will be remote on Friday. Code REMOTE.",
    )
    coordinator = mail(
        "coordinator",
        "Research Coordinator <research@synthetic.example>",
        "Study schedule",
        "The study requires 20 participants. Code PARTICIPANTS.",
    )
    thread_messages = [
        mail(
            f"thread{i}",
            "Recruiter",
            "Interview conversation",
            f"Conversation message {i}. Code THREAD{i}.",
            age=8 - i,
        )
        for i in range(1, 9)
    ]
    yesterday = calendar_window("yesterday", now=now, timezone_name=zone)
    uconn.received_at = datetime.fromtimestamp(int(yesterday[0]) + 3601, timezone.utc)
    previous_week = calendar_window("last_week", now=now, timezone_name=zone)
    john.received_at = datetime.fromtimestamp(int(previous_week[0]) + 3601, timezone.utc)

    cases = [
        {
            "query": "Find the email John sent me last week.",
            "mail": [john, newsletter],
            "ids": ["john"],
            "terms": ["FRIDAY"],
            "operators": ["from:", "after:", "before:"],
        },
        {
            "query": "Summarize my five latest job application responses.",
            "mail": [*reversed(jobs), newsletter],
            "ids": [f"job{i}" for i in range(1, 6)],
            "terms": [f"JOB{i}" for i in range(1, 6)],
        },
        {
            "query": "What emails did I receive from UConn yesterday?",
            "mail": [uconn, newsletter],
            "ids": ["uconn"],
            "terms": ["TUESDAY"],
            "operators": ["from:", "after:", "before:"],
        },
        {
            "query": "Find the most recent email mentioning AWS.",
            "mail": [
                mail("aws-old", "Cloud team", "AWS update", "The AWS migration started.", age=10),
                aws,
            ],
            "ids": ["aws"],
            "terms": ["MIGRATION"],
            "operators": ["aws"],
        },
        {
            "query": "What did the recruiter say about my interview?",
            "mail": [recruiter, newsletter],
            "ids": ["recruiter"],
            "terms": ["REMOTE"],
        },
        {
            "query": "Summarize the last five messages in this email thread.",
            "mail": [recruiter],
            "ids": [f"thread{i}" for i in range(4, 9)],
            "terms": [f"THREAD{i}" for i in range(4, 9)],
            "thread": True,
        },
        {
            "query": "Compare the research coordinator's email with information in my uploaded document.",
            "mail": [coordinator, newsletter],
            "ids": ["coordinator"],
            "terms": ["PARTICIPANTS", "30"],
            "document": True,
        },
    ]

    for case in cases:

        def operation(case=case):
            queries = []
            read_ids = []
            thread_counts = []
            docs_calls = []
            full = {email.id: email for email in [*case["mail"], *thread_messages]}

            def search(sub, query, **kwargs):
                assert sub == "synthetic-evaluation"
                queries.append(query)
                candidates = [
                    EmailSummary(
                        **{
                            key: value
                            for key, value in vars(email).items()
                            if key in EmailSummary.__dataclass_fields__
                        }
                    )
                    for email in case["mail"]
                ]
                candidates.sort(
                    key=lambda email: email.received_at.timestamp() if email.received_at else 0,
                    reverse=True,
                )
                return SearchPage(
                    messages=candidates, scanned_count=len(candidates), pages_fetched=1
                )

            def read(sub, message_id):
                assert sub == "synthetic-evaluation"
                read_ids.append(message_id)
                return full[message_id]

            def thread(sub, thread_id, *, max_messages=5):
                assert sub == "synthetic-evaluation" and thread_id == "conversation"
                selected = thread_messages[-max_messages:]
                thread_counts.append(max_messages)
                read_ids.extend(email.id for email in selected)
                return EmailThread(
                    id=thread_id, messages=selected, total_messages=8, truncated=True
                )

            def documents(query, *, user_sub):
                assert user_sub == "synthetic-evaluation"
                docs_calls.append(query)
                return [
                    Document(
                        page_content="The uploaded study plan requires 30 participants.",
                        metadata={"filename": "study.txt", "source_type": "upload"},
                    )
                ]

            history = []
            if case.get("thread"):
                history = [
                    HumanMessage("The recruiter's Gmail thread ID is conversation."),
                    AIMessage("I can summarize the conversation."),
                ]
            with (
                patch("agents.agent.llm", model),
                patch("tools.gmail.client.search_emails", side_effect=search),
                patch("tools.gmail.client.read_email", side_effect=read),
                patch("tools.gmail.client.read_email_thread", side_effect=thread),
                patch("tools.rag.retrieve", side_effect=documents),
            ):
                state = create_private_agent().invoke(
                    {
                        "messages": [
                            *history,
                            HumanMessage(
                                case["query"] + " Include exact evidence codes where present."
                            ),
                        ]
                    },
                    config={
                        "configurable": {"user_sub": "synthetic-evaluation"},
                        "recursion_limit": 128,
                    },
                )
            answer = message_text(state["messages"][-1].content)
            relevant = set(case["ids"])
            selected = set(read_ids)
            return {
                "answer": answer,
                "queries": queries,
                "selected_ids": read_ids,
                "selection_precision": len(selected & relevant) / len(selected) if selected else 0,
                "selection_recall": len(selected & relevant) / len(relevant),
                "full_read_count": len(read_ids),
                "search_count": len(queries),
                "thread_counts": thread_counts,
                "document_calls": len(docs_calls),
            }

        def matches(actual, case=case):
            return (
                actual["selection_precision"] == 1
                and actual["selection_recall"] == 1
                and actual["full_read_count"] == len(case["ids"])
                and all(term.casefold() in actual["answer"].casefold() for term in case["terms"])
                and all(
                    any(operator in query.casefold() for query in actual["queries"])
                    for operator in case.get("operators", [])
                )
                and (not case.get("thread") or actual["thread_counts"] == [5])
                and (not case.get("document") or actual["document_calls"] > 0)
            )

        run_case(
            f"gmail: {case['query']}",
            operation,
            {"selected_ids": case["ids"], "grounded_terms": case["terms"]},
            matches,
        )


def main() -> None:
    """Save a report even if model or ingestion setup fails."""
    results: list[dict] = []
    try:
        evaluate(results)
    except Exception as exc:
        results.append({"name": "evaluation setup", "passed": False, "error": type(exc).__name__})
    output = Path("artifacts/ai-evaluation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"model": llm.model, "results": results}, indent=2), encoding="utf-8"
    )
    if not all(result["passed"] for result in results):
        raise SystemExit("AI evaluation failed; see the synthetic evaluation report.")


if __name__ == "__main__":
    main()
