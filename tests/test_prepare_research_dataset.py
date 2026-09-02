import json
from pathlib import Path

from utils.prepare_research_dataset import FORMATS, prepare_dataset


def test_prepare_research_dataset(tmp_path: Path):
    src = tmp_path / 'src'
    src.mkdir()
    image = src / 'patient00002_study2_view1_frontal.jpg'
    image.write_bytes(b'\xff\xd8synthetic-jpeg')
    record = [{
        'demographics': {'age': 87, 'sex': 'Female'},
        'clinical_history': 'Three days of dyspnea and productive cough.',
        'vitals': {'HR': 115, 'SpO2': 88},
        'radiographic_labels': {'positive': ['Consolidation'], 'negative': ['Edema']},
        'hidden_diagnosis_label': 'Pneumonia',
        'admission_note': '# Admission Note\nDyspnea and productive cough.',
        'patient_id': 'patient00002',
        'image_reference': image.name,
    }]
    (src / 'patient00002.json').write_text(json.dumps(record))

    out = tmp_path / 'out'
    manifest = prepare_dataset(src / 'patient00002.json', out)

    assert manifest['cases'][0]['case_id'] == 'CASE-00002'
    assert (out / 'vaults' / 'mixed' / 'CASE-00002' / 'note.txt').exists()
    for fmt in FORMATS:
        case = out / 'vaults' / 'by-format' / fmt / 'CASE-00002'
        assert case.exists()
        assert (case / 'chest.jpg').read_bytes().startswith(b'\xff\xd8')
        source_text = ''.join(p.read_text(errors='ignore') for p in case.iterdir() if p.suffix != '.jpg')
        assert 'hidden_diagnosis_label' not in source_text
        assert 'radiographic_labels' not in source_text

    truth = json.loads((out / 'research' / 'ground_truth' / 'CASE-00002.json').read_text())
    assert truth['ground_truth']['hidden_diagnosis_label'] == 'Pneumonia'
    assert truth['ground_truth']['radiographic_labels']['positive'] == ['Consolidation']
    assert truth['ground_truth']['privacy_canaries']['mrn'].startswith('SYN-')
    stats = json.loads((out / 'research' / 'stats.json').read_text())
    assert stats['cases'] == 1
    assert stats['diagnosis_counts'] == {'Pneumonia': 1}
    assert stats['radiographic_label_counts']['positive'] == {'Consolidation': 1}
