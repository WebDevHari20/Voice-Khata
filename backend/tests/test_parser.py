import pytest
from nlu.normalizer import normalize_hindi_numbers

def test_hindi_numbers():
    assert normalize_hindi_numbers("teen sau chaalis") == "340"
    assert normalize_hindi_numbers("dhai sau") == "250"
