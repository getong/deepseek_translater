#!/usr/bin/env python3
"""
DeepSeek API Client - shared module for all translation scripts.
Loads API key and settings from .env file and provides a simple translation function.

.env settings (all optional except DEEPSEEK_API_KEY):
  DEEPSEEK_API_KEY     - Required. Your DeepSeek API key.
  DEEPSEEK_MODEL       - Model name (default: deepseek-v4-flash).
  DEEPSEEK_BASE_URL    - API base URL (default: https://api.deepseek.com).
  DEEPSEEK_MAX_TOKENS  - Max output tokens (default: 16384).
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

_ENV_LOADED = False


def _ensure_env_loaded():
    """Load .env file once so all DEEPSEEK_* settings are available."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    if load_dotenv is not None:
        env_path = Path(__file__).parent / ".env"
        load_dotenv(env_path, override=False)
    _ENV_LOADED = True


def get_model():
    """Return the model name from DEEPSEEK_MODEL env var, or the default."""
    _ensure_env_loaded()
    return os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)


def get_max_tokens():
    """Return max tokens from DEEPSEEK_MAX_TOKENS env var, or the default."""
    _ensure_env_loaded()
    return int(os.environ.get("DEEPSEEK_MAX_TOKENS", DEFAULT_MAX_TOKENS))


def get_base_url():
    """Return base URL from DEEPSEEK_BASE_URL env var, or the default."""
    _ensure_env_loaded()
    return os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)


def _load_api_key():
    """Load DEEPSEEK_API_KEY from .env file or environment variable."""
    global API_KEY

    _ensure_env_loaded()

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
            base_url=get_base_url(),
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
        selected_model = model or get_model()
        output_limit = max_tokens or get_max_tokens()
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
        model = get_model()
        print(f"DeepSeek API connection OK (model: {model})")
        return True
    except Exception as e:
        print(f"DeepSeek API connection failed: {e}")
        return False
