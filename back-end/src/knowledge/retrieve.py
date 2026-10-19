from knowledge.store import vector_store
from core.identity import require_identity


def retrieve(query: str, *, user_sub: str):
    require_identity(user_sub)
    retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": 4,
            "filter": {"$and": [{"user_sub": user_sub}, {"source_type": "upload"}]},
        },
    )
    return retriever.invoke(query)
