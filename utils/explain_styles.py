"""
Reformat an already-generated answer into a different explanation style,
without re-running retrieval. Cheap (one LLM call, no vector search) since
we already have a grounded answer - we're just asking for a different
register/audience.
"""

from utils.llm_config import llm

STYLE_PROMPTS = {
    "eli10": "Explain this like I'm 10 years old. Use a simple analogy, short sentences, no jargon.",
    "interview": "Rephrase this as how you'd answer it out loud in a technical job interview - "
                 "confident, structured, hitting the key points concisely.",
    "exam": "Rephrase this as a model exam answer - clear, well-structured, using precise "
            "terminology a grader would want to see.",
    "technical": "Rephrase this as a detailed technical explanation for a knowledgeable "
                 "practitioner - precise terminology, no oversimplification.",
}


def explain(answer_text: str, question: str, style: str) -> str:
    style = style if style in STYLE_PROMPTS else "technical"
    instruction = STYLE_PROMPTS[style]

    prompt = f"""
    Original question: {question}
    Original answer: {answer_text}

    {instruction}

    Keep the same factual content - only change the tone/framing/level of detail.
    """
    response = llm.invoke(prompt)
    return response.content
