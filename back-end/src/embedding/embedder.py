from langchain_ollama import OllamaEmbeddings

embeddings = OllamaEmbeddings(
    model="nomic-embed-text:latest",
) 

def embed(chunks):
    texts = [c.page_content for c in chunks]
    return embeddings.embed_documents(texts)