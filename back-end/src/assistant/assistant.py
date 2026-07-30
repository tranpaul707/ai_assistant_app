from langchain_core.prompts import ChatPromptTemplate
from llm.client import llm

def handle_query(query):
    template = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful and kind AI assistant who enjoys responding in a helpful tone"),
        ("human", "{question}")
        ])
    
    prompt = template.invoke({"question": query})

    for chunk in llm.stream(prompt):
        yield chunk