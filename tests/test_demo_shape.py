from pathlib import Path


def test_demo_is_text_plus_jpg():
    root = Path(__file__).parents[1] / 'demo'
    for case in ('CASE-001', 'CASE-002'):
        assert (root / case / 'note.txt').exists()
        assert (root / case / 'chest.jpg').exists()
        assert (root / case / 'chest.jpg').read_bytes()[:2] == b'\xff\xd8'
