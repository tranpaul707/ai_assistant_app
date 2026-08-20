from langchain_core.prompts import ChatPromptTemplate
from llm.client import llm

def handle_query(query, context=None):
    template = ChatPromptTemplate.from_messages([
        ("system",
         "You are a kind AI assistant who enjoys responding in a helpful tone. "
         "Use the following retrieved content when answering if it is present; "
         "if it is empty or None, ignore it and don't mention about retrieving any content, and answer to the best of your own ability\n\n"
         "Also note, if there is no response after human, please kindly ask to if there was any question they needed"
         "Retrieved content:\n{context}"),
        ("human", "{question}"),
    ])

    prompt = template.invoke({"question": query, "context": context or ""})


    for chunk in llm.stream(prompt):
        yield chunk