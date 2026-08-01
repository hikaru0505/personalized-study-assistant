"""
Generate a concise summary of the uploaded document.
"""

from utils.llm_config import llm


def generate_summary(text: str) -> str:
    """
    text: the full extracted document text. We only send the first ~4000
    characters to the model to keep the prompt small and fast; for very
    long documents you'd want to chunk + map-reduce summarize instead.
    """
    prompt = f"""
    Summarize the following study material in clear, well-organized bullet
    points that a student could use to quickly review the material.

    Content:
    {text[:4000]}
    """
    response = llm.invoke(prompt)
    # BUG in original code: response.contnet (typo) -> AttributeError
    return response.content
