"""Conservative deterministic-first mathematical answer scoring."""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from fractions import Fraction
from typing import Dict, Optional, Tuple

import sympy

from .models import (
    AdjudicationStatus,
    Episode,
    LabelValue,
    OutcomeLabel,
    ScorerType,
)

SCORER_NAME = "mathaudit_deterministic"
SCORER_VERSION = "0.1.0"


def _strip_outer_math(text: str) -> str:
    value = text.strip()
    wrappers = (("$", "$"), ("\\(", "\\)"), ("\\[", "\\]"))
    changed = True
    while changed:
        changed = False
        for left, right in wrappers:
            if value.startswith(left) and value.endswith(right) and len(value) > len(left) + len(right):
                value = value[len(left) : -len(right)].strip()
                changed = True
    return value


def _last_boxed(text: str) -> Optional[str]:
    marker = "\\boxed{"
    start = text.rfind(marker)
    if start < 0:
        return None
    depth = 1
    cursor = start + len(marker)
    for index in range(cursor, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[cursor:index].strip()
    return None


def extract_answer(text: str) -> str:
    """Extract a conservative final-answer candidate while preserving raw text."""

    value = str(text or "").strip()
    if not value:
        return ""
    boxed = _last_boxed(value)
    if boxed:
        return boxed
    patterns = (
        r"(?:最终答案|答案)\s*[：:]\s*(.+)",
        r"(?:final\s+answer|answer)\s*[：:]\s*(.+)",
    )
    for pattern in patterns:
        matches = re.findall(pattern, value, flags=re.IGNORECASE)
        if matches:
            return str(matches[-1]).strip().splitlines()[0].strip()
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) == 1:
        return _strip_outer_math(lines[0])
    return ""


def normalize_surface(text: str) -> str:
    value = _strip_outer_math(str(text or ""))
    value = value.replace("\\left", "").replace("\\right", "")
    value = value.replace("−", "-").replace("–", "-")
    value = value.replace("\\,", "").replace("\\!", "")
    value = re.sub(r"\s+", "", value)
    return value.strip(".，。")


def _latex_to_basic_expression(text: str) -> str:
    value = normalize_surface(text)
    simple_braces = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
    while simple_braces.search(value):
        value = simple_braces.sub(r"((\1)/(\2))", value)
    value = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", value)
    value = value.replace("\\cdot", "*").replace("\\times", "*")
    value = value.replace("\\pi", "pi")
    value = value.replace("^", "**")
    value = re.sub(r"(?<=\d)(?=[A-Za-z])", "*", value)
    value = re.sub(r"(?<=[0-9)])(?=\()", "*", value)
    value = re.sub(r"(?<=\))(?=[A-Za-z0-9])", "*", value)
    return value


_FUNCTIONS = {
    "sqrt": sympy.sqrt,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "exp": sympy.exp,
    "log": sympy.log,
    "abs": sympy.Abs,
}


def _safe_sympy_ast(node: ast.AST, symbols: Dict[str, sympy.Symbol]) -> sympy.Expr:
    if isinstance(node, ast.Expression):
        return _safe_sympy_ast(node.body, symbols)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return sympy.Rational(str(node.value))
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return sympy.pi
        if node.id in {"e", "E"}:
            return sympy.E
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", node.id):
            raise ValueError("unsupported symbol")
        symbols.setdefault(node.id, sympy.Symbol(node.id))
        return symbols[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _safe_sympy_ast(node.operand, symbols)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _safe_sympy_ast(node.left, symbols)
        right = _safe_sympy_ast(node.right, symbols)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        raise ValueError("unsupported binary operator")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id.lower())
        if function is None or node.keywords:
            raise ValueError("unsupported function")
        arguments = [_safe_sympy_ast(argument, symbols) for argument in node.args]
        return function(*arguments)
    raise ValueError("unsupported syntax")


def safe_symbolic_expression(text: str) -> Optional[sympy.Expr]:
    value = _latex_to_basic_expression(text)
    if not value or len(value) > 300 or "__" in value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_+\-*/().,]*", value):
        return None
    try:
        tree = ast.parse(value, mode="eval")
        return _safe_sympy_ast(tree, {})
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
        return None


def _looks_like_symbolic_math(text: str) -> bool:
    value = _latex_to_basic_expression(text)
    if re.search(r"[0-9+\-*/()]", value):
        return True
    if re.fullmatch(r"[A-Za-z]", value):
        return True
    return any("%s(" % name in value.lower() for name in _FUNCTIONS)


def _fraction(text: str) -> Optional[Fraction]:
    value = _latex_to_basic_expression(text)
    if value.endswith("%"):
        value = value[:-1]
        scale = Fraction(1, 100)
    else:
        scale = Fraction(1, 1)
    if not re.fullmatch(r"[+\-]?(?:\d+(?:\.\d+)?|\d+/\d+)", value):
        return None
    try:
        return Fraction(value) * scale
    except (ValueError, ZeroDivisionError):
        return None


def compare_answers(candidate: str, gold: str, answer_type: Optional[str] = None) -> Tuple[LabelValue, Optional[ScorerType], str, str]:
    """Return label, scorer type, normalized candidate, and rule identifier."""

    extracted = extract_answer(candidate)
    normalized_candidate = normalize_surface(extracted)
    normalized_gold = normalize_surface(extract_answer(gold) or gold)
    if not normalized_candidate:
        return LabelValue.abstain, None, "", "empty_or_no_extractable_answer"
    if normalized_candidate == normalized_gold:
        return LabelValue.correct, ScorerType.exact, normalized_candidate, "surface_exact_v1"

    candidate_number = _fraction(normalized_candidate)
    gold_number = _fraction(normalized_gold)
    if candidate_number is not None and gold_number is not None:
        value = LabelValue.correct if candidate_number == gold_number else LabelValue.incorrect
        return value, ScorerType.numeric, normalized_candidate, "rational_numeric_v1"

    candidate_expression = (
        safe_symbolic_expression(normalized_candidate)
        if _looks_like_symbolic_math(normalized_candidate)
        else None
    )
    gold_expression = (
        safe_symbolic_expression(normalized_gold)
        if _looks_like_symbolic_math(normalized_gold)
        else None
    )
    if candidate_expression is not None and gold_expression is not None:
        try:
            equivalent = sympy.simplify(candidate_expression - gold_expression) == 0
        except Exception:
            equivalent = False
        value = LabelValue.correct if equivalent else LabelValue.incorrect
        return value, ScorerType.symbolic, normalized_candidate, "safe_symbolic_ast_v1"

    if answer_type and answer_type.lower() in {"categorical", "choice", "boolean", "text"}:
        simple = re.compile(r"[A-Za-z0-9_\- ]{1,80}")
        if simple.fullmatch(normalized_candidate) and simple.fullmatch(normalized_gold):
            return LabelValue.incorrect, ScorerType.exact, normalized_candidate, "registered_categorical_v1"

    return LabelValue.unscorable, None, normalized_candidate, "unsupported_deterministic_form"


def score_episode(episode: Episode) -> Episode:
    """Return a deep copy with deterministic labels appended for produced evidence."""

    scored = episode.model_copy(deep=True)
    gold = scored.audit_only.gold
    if gold is None:
        return scored
    existing_ids = {label.label_id for label in scored.labels}
    for item in scored.evidence:
        value, scorer_type, normalized, rule_id = compare_answers(
            item.content.normalized_answer or item.content.text or "",
            gold,
            scored.problem.answer_type,
        )
        item.content.normalized_answer = normalized or None
        label_id = "label:deterministic:%s" % item.evidence_id
        if label_id in existing_ids:
            continue
        if scorer_type is None:
            scorer_type = ScorerType.exact
        scored.labels.append(
            OutcomeLabel(
                label_id=label_id,
                target_type="evidence",
                target_id=item.evidence_id,
                value=value,
                scorer_type=scorer_type,
                scorer_name=SCORER_NAME,
                scorer_version=SCORER_VERSION,
                rule_id=rule_id,
                decision_path=["extract", rule_id],
                confidence=1.0 if value != LabelValue.unscorable else None,
                adjudication_status=(
                    AdjudicationStatus.pending
                    if value == LabelValue.unscorable
                    else AdjudicationStatus.not_needed
                ),
                created_at=datetime.now(timezone.utc),
            )
        )
    return scored
