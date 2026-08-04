# Entry point for the RAG pipeline
from pathlib import Path
from ollama import embed, embeddings
from documents.document import load_file
from chunking import textsplitter
from chunking.textsplitter import chunk_text
from embedding.embedder import embed
from vectorstore import database
from vectorstore.database import vector_store

def rag_pipeline():

    # 1. Load file
    docs = load_file("file.txt")
    print(f"Loaded {len(docs)} document(s)")

    # 2. Chunk out document
    chunks = chunk_text(docs)
    
    # 3. Embeds chunks and store the embeddings inside vector_store
    ids = [f"filetxt-{i}" for i in range(len(chunks))]
    vector_store.add_documents(documents=chunks, ids=ids)

if __name__ == "__main__":
#    results = vector_store.get()
#    print(results.keys())          # often: documents, metadatas, ids, embeddings?
#    print(len(results["ids"]))
#    print(results["ids"][:5])      # first few ids
#    print(results["documents"][:2])  # first chunk texts

    # 1. Load file
    count = 0
    docs = load_file("file.txt")
    print(f"Loaded {len(docs)} document(s)")

    # 2. Chunk out document
    chunks = chunk_text(docs)

    for chunk in chunks:
        count += 1
    
    print(count)