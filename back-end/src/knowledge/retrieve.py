from knowledge.store import vector_store


def retrieve(query):
    retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 4},
    )
    return retriever.invoke(query)
