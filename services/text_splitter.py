from langchain_text_splitters import RecursiveCharacterTextSplitter


def split_text(text: str) -> list[str]:
    """
   Split document into meaningful chunks.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=160,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
            ""
        ]
    )

    return splitter.split_text(text)
