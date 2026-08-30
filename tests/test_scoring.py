# SPDX-License-Identifier: MIT

from mathaudit.models import LabelValue, ScorerType
from mathaudit.scoring import compare_answers, extract_answer, safe_symbolic_expression


def test_extracts_last_boxed_answer():
    assert extract_answer(r"work \boxed{2} more \boxed{3}") == "3"


def test_numeric_equivalence():
    label, scorer, normalized, rule = compare_answers(r"\boxed{1/2}", "0.5")
    assert label == LabelValue.correct
    assert scorer == ScorerType.numeric
    assert normalized == "1/2"
    assert rule == "rational_numeric_v1"


def test_symbolic_equivalence():
    label, scorer, _, _ = compare_answers("x^2 + 2*x + 1", "(x+1)^2")
    assert label == LabelValue.correct
    assert scorer == ScorerType.symbolic


def test_numeric_inequality_is_incorrect():
    label, scorer, _, _ = compare_answers("2", "3")
    assert label == LabelValue.incorrect
    assert scorer == ScorerType.numeric


def test_unsupported_text_is_not_forced_wrong():
    label, scorer, _, _ = compare_answers("a plausible proof", "a different proof")
    assert label == LabelValue.unscorable
    assert scorer is None


def test_symbolic_parser_rejects_code_execution_syntax():
    assert safe_symbolic_expression("__import__('os').system('echo unsafe')") is None
