from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_text(document):
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", chunk_size=500, chunk_overlap=100
    )
    texts = text_splitter.split_documents(document)

    return texts

