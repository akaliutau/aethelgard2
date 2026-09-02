from __future__ import annotations

import os

from dotenv import load_dotenv

from .errors import ModelAccessError

load_dotenv()


def hf_token() -> str | None:
    return os.getenv('HF_TOKEN') or None


def gated_model_help(model_name: str, exc: BaseException) -> ModelAccessError:
    return ModelAccessError(
        f'Cannot access gated Hugging Face model {model_name!r}. '
        'Open the model page while logged in and accept its license/terms, then authenticate. '
        'Recommended: export HF_TOKEN=hf_... or run `hf auth login --token "$HF_TOKEN"`. '
        'See README.md → "Hugging Face gated models". '
        f'Original error: {exc}'
    )
