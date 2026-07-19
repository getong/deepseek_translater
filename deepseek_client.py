#!/usr/bin/env python3
"""
DeepSeek API Client - shared module for all translation scripts.
Loads API key from .env file and provides a simple translation function.
"""

import os
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

_client = None
API_KEY = None
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_TOKENS = 16384


def _load_api_key():
    """Load DEEPSEEK_API_KEY from .env file or environment variable."""
    global API_KEY

    if load_dotenv is not None:
        env_path = Path(__file__).parent / ".env"
        load_dotenv(env_path, override=False)

    API_KEY = os.environ.get("DEEPSEEK_API_KEY")
    if not API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not found. Set it in .env or the environment."
        )


def get_client():
    """Get or create the shared OpenAI client configured for DeepSeek."""
    global _client
    if _client is None:
        if OpenAI is None:
            raise RuntimeError(
                "The 'openai' package is not installed. Run ./translatebook.sh "
                "to install project dependencies."
            )
        _load_api_key()
        _client = OpenAI(
            api_key=API_KEY,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        )
    return _client


def translate(text, prompt=None, model=None, timeout=180, max_tokens=None):
    """
    Send a translation request to DeepSeek API.

    Args:
        text: Text to translate, optionally including detailed instructions.
        prompt: Optional system prompt.
        model: DeepSeek model name. Defaults to DEEPSEEK_MODEL or V4 Flash.
        timeout: Request timeout in seconds.
        max_tokens: Maximum output tokens. Defaults to DEEPSEEK_MAX_TOKENS or 16384.

    Returns:
        The translated text string, or None on failure.
    """
    try:
        client = get_client()
        selected_model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        output_limit = max_tokens or int(
            os.environ.get("DEEPSEEK_MAX_TOKENS", DEFAULT_MAX_TOKENS)
        )
        response = client.chat.completions.create(
            model=selected_model,
            messages=[
                {
                    "role": "system",
                    "content": prompt or (
                        "You are a professional translator. Translate accurately "
                        "while preserving all source formatting."
                    ),
                },
                {"role": "user", "content": text},
            ],
            timeout=timeout,
            max_tokens=output_limit,
            extra_body={"thinking": {"type": "disabled"}},
        )
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise RuntimeError(
                f"DeepSeek response did not finish normally: {choice.finish_reason}"
            )
        content = choice.message.content
        if not content:
            raise RuntimeError("DeepSeek returned an empty response")
        return content.strip()
    except Exception as e:
        print(f"    DeepSeek API error: {e}")
        return None


def check_api():
    """Quick health-check: verify the API key works."""
    try:
        client = get_client()
        client.models.list()
        model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        print(f"DeepSeek API connection OK (model: {model})")
        return True
    except Exception as e:
        print(f"DeepSeek API connection failed: {e}")
        return False
