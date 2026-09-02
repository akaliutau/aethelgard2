from aethelgard.config import VaultConfig
from aethelgard.server import runtime_config


def test_worker_can_override_execution_device_without_model_name(monkeypatch):
    config = VaultConfig()
    original_model = config.extractor.model
    original_text_model = config.embeddings.text_model
    original_image_model = config.embeddings.image_model

    monkeypatch.setenv('AETHELGARD_WORKER_DEVICE', 'cuda')
    runtime = runtime_config(config)

    assert runtime.extractor.device == 'cuda'
    assert runtime.embeddings.device == 'cuda'
    assert runtime.extractor.model == original_model
    assert runtime.embeddings.text_model == original_text_model
    assert runtime.embeddings.image_model == original_image_model
    assert runtime.source.kind == 'local'
