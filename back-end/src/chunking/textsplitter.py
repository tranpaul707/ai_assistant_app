from langchain_text_splitters import CharacterTextSplitter
from documents.document import load_file


def chunk_text(document):
    text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", chunk_size=1000, chunk_overlap=0
    )
    texts = text_splitter.split_documents(document)

    return texts

