from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from ...auth import hf_token


class ClinicalFact(BaseModel):
    """One atomic extracted fact. Paths are semantic, not a fixed medical schema."""

    path: str = Field(
        min_length=1,
        description='Dot-separated semantic path, e.g. presentation.symptoms or treatment.procedure.',
    )
    value: str | int | float | bool = Field(
        description='One faithful atomic value copied or normalized from the source record.',
    )


class ClinicalFactBatch(BaseModel):
    facts: list[ClinicalFact] = Field(
        default_factory=list,
        description='Faithful clinical facts extracted from the source. Repeat a path for multiple values.',
    )


def facts_to_evidence(batch: ClinicalFactBatch) -> dict[str, object]:
    """Materialize dynamic dot-path facts into the vault's flexible evidence dictionary."""

    evidence: dict[str, object] = {}
    for fact in batch.facts:
        parts = [p.strip() for p in fact.path.split('.') if p.strip()]
        if not parts:
            continue

        cursor: dict[str, object] = evidence
        for part in parts[:-1]:
            current = cursor.get(part)
            if not isinstance(current, dict):
                current = {}
                cursor[part] = current
            cursor = current

        key = parts[-1]
        if key not in cursor:
            cursor[key] = fact.value
        else:
            current = cursor[key]
            if isinstance(current, list):
                current.append(fact.value)
            else:
                cursor[key] = [current, fact.value]

    return evidence


@dataclass(slots=True)
class QwenStructuredModel:
    """Reliable local structured extraction using Qwen3 + constrained decoding.

    Outlines constrains model output to ClinicalFactBatch. The stable fact envelope
    is intentionally separate from the dynamic evidence dictionary materialized by
    Aethelgard.
    """

    model_name: str = 'Qwen/Qwen3-4B'
    device: str = 'cpu'
    max_new_tokens: int = 1024
    _tokenizer: Any = field(default=None, init=False, repr=False)
    _model: Any = field(default=None, init=False, repr=False)
    _structured: Any = field(default=None, init=False, repr=False)

    @property
    def fingerprint(self) -> str:
        return f'model:qwen-structured:{self.model_name}:facts-v1'

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        try:
            import outlines
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                'Qwen structured extraction requires `pip install -e ".[models]"`'
            ) from exc

        token = hf_token()
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, token=token)

        kwargs: dict[str, object] = {'token': token, 'dtype': 'auto'}
        if self.device == 'auto':
            kwargs['device_map'] = 'auto'
            self._model = AutoModelForCausalLM.from_pretrained(self.model_name, **kwargs)
        else:
            self._model = AutoModelForCausalLM.from_pretrained(self.model_name, **kwargs).to(self.device)

        self._model.eval()
        self._structured = outlines.from_transformers(self._model, self._tokenizer)

    def call(self, *, prompt: str, function_name: str, description: str) -> dict[str, object]:
        self._ensure_loaded()

        messages = [
            {
                'role': 'system',
                'content': (
                    f'{description} '
                    'Extract atomic clinical facts only. Do not include direct identifiers. '
                    'Use concise dot-separated semantic paths. Repeat the same path when a field has multiple values. '
                    'Do not infer facts that are not supported by the source.'
                ),
            },
            {'role': 'user', 'content': prompt},
        ]
        print(messages)
        template_kwargs: dict[str, object] = {
            'tokenize': False,
            'add_generation_prompt': True,
        }
        # Qwen3 supports disabling the reasoning channel. Older compatible
        # tokenizers simply ignore the absence of this option.
        try:
            rendered = self._tokenizer.apply_chat_template(
                messages,
                enable_thinking=False,
                **template_kwargs,
            )
        except TypeError:
            rendered = self._tokenizer.apply_chat_template(messages, **template_kwargs)

        raw = self._structured(
            rendered,
            ClinicalFactBatch,
            max_new_tokens=self.max_new_tokens,
        )
        print(raw)
        batch = (
            ClinicalFactBatch.model_validate_json(raw)
            if isinstance(raw, str)
            else ClinicalFactBatch.model_validate(raw)
        )
        evidence = facts_to_evidence(batch)
        if not evidence:
            raise ValueError('Qwen extractor returned no clinical facts')
        return {'evidence': evidence}
