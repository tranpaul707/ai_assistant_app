from langchain_ollama import OllamaEmbeddings

embeddings = OllamaEmbeddings(
    model="nomic-embed-text:latest",
) 

def embed(chunks):
    vector = embeddings.embed_query(chunks[0].page_content)

    return vector