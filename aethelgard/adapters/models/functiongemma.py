from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ...auth import gated_model_help, hf_token

_CALL_RE = re.compile(
    r'<start_function_call>call:(?P<name>[A-Za-z0-9_]+)\{(?P<body>.*?)\}<end_function_call>',
    re.DOTALL,
)
_ESCAPED_ARG_RE = re.compile(r'(?P<key>[A-Za-z0-9_]+):<escape>(?P<value>.*?)<escape>', re.DOTALL)
_JSON_ARG_RE = re.compile(r'(?P<key>[A-Za-z0-9_]+):(?P<value>\{.*\}|\[.*\])', re.DOTALL)


def parse_functiongemma_call(text: str, expected_name: str) -> dict[str, object]:
    match = _CALL_RE.search(text)
    if not match:
        raise ValueError(f'FunctionGemma did not emit a function call: {text[:320]!r}')
    if match.group('name') != expected_name:
        raise ValueError(f'Expected function {expected_name!r}, got {match.group("name")!r}')

    body = match.group('body').strip()
    structured = _JSON_ARG_RE.fullmatch(body)
    if structured:
        return {structured.group('key'): json.loads(structured.group('value'))}

    args = {m.group('key'): m.group('value') for m in _ESCAPED_ARG_RE.finditer(body)}
    if args:
        return args

    raise ValueError(f'FunctionGemma emitted no parsable arguments: {text[:320]!r}')


@dataclass(slots=True)
class FunctionGemmaToolModel:
    """270M local structured-function backend.

    The model is intentionally hidden behind StructuredToolModel. A future
    task-specific fine-tune can use the same adapter without changing the vault.
    """

    model_name: str = 'google/functiongemma-270m-it'
    device: str = 'cpu'
    max_new_tokens: int = 768
    _processor: object | None = field(default=None, init=False, repr=False)
    _model: object | None = field(default=None, init=False, repr=False)

    @property
    def fingerprint(self) -> str:
        return f'model:functiongemma:{self.model_name}:v1'

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as exc:
            raise RuntimeError('FunctionGemma requires `pip install -e .[models]`') from exc
        token = hf_token()
        try:
            self._processor = AutoProcessor.from_pretrained(self.model_name, token=token)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                token=token,
                dtype=torch.float32 if self.device == 'cpu' else 'auto',
            ).to(self.device)
            self._model.eval()
        except Exception as exc:
            if 'gated' in str(exc).lower() or '401' in str(exc) or 'restricted' in str(exc).lower():
                raise gated_model_help(self.model_name, exc) from exc
            raise

    def call(self, *, prompt: str, function_name: str, description: str) -> dict[str, object]:
        self._ensure_loaded()
        import torch

        tool = {
            'type': 'function',
            'function': {
                'name': function_name,
                'description': description,
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'evidence': {
                            'type': 'object',
                            'description': 'Flexible structured clinical evidence extracted faithfully from the source.',
                            'additionalProperties': True,
                        }
                    },
                    'required': ['evidence'],
                },
            },
        }
        messages = [
            {'role': 'developer', 'content': 'You are a model that can do function calling with the following functions'},
            {'role': 'user', 'content': prompt},
        ]
        inputs = self._processor.apply_chat_template(
            messages,
            tools=[tool],
            add_generation_prompt=True,
            return_dict=True,
            return_tensors='pt',
        ).to(self._model.device)
        with torch.inference_mode():
            output = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=getattr(self._processor, 'eos_token_id', None),
            )
        generated = output[0][inputs['input_ids'].shape[-1]:]
        text = self._processor.decode(generated, skip_special_tokens=False)
        print(text)
        return parse_functiongemma_call(text, function_name)
