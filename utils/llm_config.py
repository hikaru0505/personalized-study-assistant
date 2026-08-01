"""
Centralized LLM configuration.

Why this file exists:
- The original code created a *new* ChatGroq client in every single module
  (flashcards, quiz, summary, rag_chat) and each one had the model name typed
  out by hand -> that's how the "llama-3.3.-70b-versatile" typo (extra dot)
  crept in and broke every LLM call.
- By creating ONE client here and importing it everywhere else, we fix the
  bug in a single place and avoid re-authenticating/re-instantiating the
  Groq client on every function call.
"""

import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

# Load variables from .env (GROQ_API_KEY, etc.) as early as possible.
load_dotenv()

# NOTE: correct model name is "llama-3.3-70b-versatile"
# (the original code had "llama-3.3.-70b-versatile" -> invalid model id)
MODEL_NAME = "llama-3.3-70b-versatile"

if not os.getenv("GROQ_API_KEY"):
    # Fail loudly and early instead of a confusing traceback later
    # when the first LLM call is made.
    raise RuntimeError(
        "GROQ_API_KEY is not set. Create a .env file (see .env.example) "
        "and add GROQ_API_KEY=your_key_here"
    )

# Single shared LLM instance used across the whole app.
llm = ChatGroq(
    model_name=MODEL_NAME,
    temperature=0.3,  # a bit of creativity, but still mostly factual/consistent
)
