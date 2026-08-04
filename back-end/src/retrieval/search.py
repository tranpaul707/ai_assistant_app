from vectorstore.database import vector_store

def retrieve(query):
    retriever = vector_store.as_retriever(
    search_type="similarity_score_threshold", search_kwargs={"score_threshold": 0.9}
    )

    documents = retriever.invoke(query)

    return documents