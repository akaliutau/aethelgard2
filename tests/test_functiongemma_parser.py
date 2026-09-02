from aethelgard.adapters.models.functiongemma import parse_functiongemma_call


def test_functiongemma_parser():
    text = '<start_function_call>call:emit_clinical_evidence{json:<escape>{"diagnosis":"x"}<escape>}<end_function_call>'
    result = parse_functiongemma_call(text, 'emit_clinical_evidence')
    assert result['json'] == '{"diagnosis":"x"}'
