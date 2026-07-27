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

if __name__ == "__main__":
    for chunk in handle_query("What is React?"):
        print(chunk, end="", flush=True)
    print()  # final newline