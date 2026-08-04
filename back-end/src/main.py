# Entry point for the RAG pipeline
from pathlib import Path

from documents.document import load_file
from chunking import textsplitter
from chunking.textsplitter import chunk_text

def rag_pipeline():
    docs = load_file("file.txt")
    print(f"Loaded {len(docs)} document(s)")

    # Chunking comes next once split_text accepts Document lists and returns chunks
    chunks = chunk_text(docs)
    for chunk in chunks:
        print(chunk)

if __name__ == "__main__":
    rag_pipeline()
