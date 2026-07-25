from langchain_core.prompts import ChatPromptTemplate, prompt
from langchain_ollama.llms import OllamaLLM
import asyncio

llm = OllamaLLM(model="llama3.1", temperature=0)

async def handle_query(query):
    template = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful and kind AI assistant who enjoys responding in a helpful tone"),
        ("human", "{question}")
        ])
    
    prompt = template.invoke({"question": query})

    response = await llm.ainvoke(prompt)

    print(response)

if __name__ == "__main__":
    asyncio.run(handle_query("What is React?"))