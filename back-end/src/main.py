# Entry point for the RAG pipeline
from pathlib import Path
from documents.document import load_file
from chunking.textsplitter import chunk_text
from retrieval.search import retrieve
from vectorstore.database import vector_store
from assistant.assistant import handle_query

def rag_pipeline(query):

    # 1. Load file
    docs = load_file("file.txt")
    print(f"Loaded {len(docs)} document(s)")

    # 2. Chunk out document
    chunks = chunk_text(docs)
    
    # 3. Embeds chunks and store the embeddings inside vector_store
    ids = [f"filetxt-{i}" for i in range(len(chunks))]
    vector_store.add_documents(documents=chunks, ids=ids)

    # 4. Retrieve Documents if relevant
    documents = retrieve(query)

    # 5. Feed documents to LLM
    if not documents:
        response = handle_query(query)
    else:
        response = handle_query(query, documents)

    return response


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