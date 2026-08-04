from langchain_core.prompts import ChatPromptTemplate
from llm.client import llm

def handle_query(query, context=None):
    template = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful and kind AI assistant who enjoys responding in a helpful tone"),
        ("context", "Here is retrieved content related to this query, use it as information when creating a output, {context}, if context is None, ignore the context"),
        ("human", "{question}")
        ])
    
    prompt = template.invoke({"question": query, "context" : context})

    for chunk in llm.stream(prompt):
        yield chunk