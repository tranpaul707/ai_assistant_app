# Entry point for the RAG pipeline
from documents.document import load_file
from chunking.textsplitter import split_text

if __name__ == "__main__":
