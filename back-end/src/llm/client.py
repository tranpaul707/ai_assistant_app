from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM
import asyncio

llm = OllamaLLM(model="llama3.1", temperature=0)

prompt = None

async def wait_for_prompt():
    global prompt
    while prompt is None:
        print("Waiting for response")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(wait_for_prompt())
    
