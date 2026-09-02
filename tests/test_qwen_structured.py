from aethelgard.adapters.models.qwen import ClinicalFact, ClinicalFactBatch, facts_to_evidence
from aethelgard.config import VaultConfig


def test_facts_materialize_to_dynamic_evidence_dict():
    result = facts_to_evidence(ClinicalFactBatch(facts=[
        ClinicalFact(path='presentation.symptoms', value='dyspnea'),
        ClinicalFact(path='presentation.symptoms', value='pleuritic chest pain'),
        ClinicalFact(path='vitals.oxygen_saturation', value=87),
        ClinicalFact(path='diagnosis', value='spontaneous pneumothorax'),
        ClinicalFact(path='treatment.procedure', value='tube thoracostomy'),
    ]))
    assert result == {
        'presentation': {'symptoms': ['dyspnea', 'pleuritic chest pain']},
        'vitals': {'oxygen_saturation': 87},
        'diagnosis': 'spontaneous pneumothorax',
        'treatment': {'procedure': 'tube thoracostomy'},
    }


def test_qwen_is_default_extractor():
    config = VaultConfig()
    assert config.extractor.kind == 'qwen'
    assert config.extractor.model == 'Qwen/Qwen3-4B'
