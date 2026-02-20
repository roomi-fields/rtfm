"""Reusable Gemini LLM client for rtfm.

Extracted and generalized from src/tagger.py.
"""

import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class LLMConfig:
    """Configuration for LLM calls."""

    api_key: str = ""
    model: str = "gemini-2.0-flash-exp"
    temperature: float = 0.2
    max_output_tokens: int = 2048
    timeout: int = 30
    max_retries: int = 3

    @classmethod
    def from_env(cls, **overrides) -> "LLMConfig":
        """Create config from environment variables."""
        config = cls(api_key=os.environ.get("GEMINI_API_KEY", ""))
        for k, v in overrides.items():
            setattr(config, k, v)
        return config


def call_gemini(prompt: str, config: Optional[LLMConfig] = None) -> str:
    """Call Gemini API with retry on rate limit.

    Args:
        prompt: The prompt to send.
        config: LLM configuration. Uses env defaults if None.

    Returns:
        The generated text response.

    Raises:
        ValueError: If API key is not set.
        RuntimeError: If all retries fail.
    """
    if config is None:
        config = LLMConfig.from_env()

    if not config.api_key:
        raise ValueError("GEMINI_API_KEY not set. Pass it via config or environment variable.")

    url = GEMINI_API_URL.format(model=config.model) + f"?key={config.api_key}"

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": config.temperature,
            "maxOutputTokens": config.max_output_tokens,
        },
    }).encode("utf-8")

    last_error = None
    for attempt in range(config.max_retries):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=config.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429:
                wait = 2 ** attempt
                time.sleep(wait)
            else:
                raise RuntimeError(f"Gemini API error (HTTP {e.code}): {e}") from e
        except Exception as e:
            raise RuntimeError(f"Gemini API error: {e}") from e

    raise RuntimeError(f"Gemini API: max retries exceeded. Last error: {last_error}")
