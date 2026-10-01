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
            )
            ingest(
                [Document(page_content="The cafeteria serves lentil soup on Tuesday.")],
                "cafeteria.txt",
            )
            run_case(
                "retrieval: launch source ranks first",
                lambda: retrieve("When does Project Aurora launch?")[0].metadata["source"],
                "aurora.txt",
                lambda value: value == "aurora.txt",
            )
            context = "\n".join(
                doc.page_content for doc in retrieve("When does Project Aurora launch?")
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
