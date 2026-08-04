# Entry point for the RAG pipeline
from pathlib import Path

from ollama import embed, embeddings

from documents.document import load_file
from chunking import textsplitter
from chunking.textsplitter import chunk_text
from embedding.embedder import embed
def rag_pipeline():

    # 1. Load file
    docs = load_file("file.txt")
    print(f"Loaded {len(docs)} document(s)")

    # 2. Chunk out document
    chunks = chunk_text(docs)
    
    # 3. Embed the chunks into vectors
    vector = embed(chunks)
    print(vector)

if __name__ == "__main__":
    rag_pipeline()
