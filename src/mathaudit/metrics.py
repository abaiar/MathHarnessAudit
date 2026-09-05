# SPDX-License-Identifier: MIT

"""Outcome-linked evidence dependence and transition metrics."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.stats import beta as beta_distribution

from .models import Episode, LabelValue, ObservationOutcome, OutcomeLabel, SourceType

_LABEL_PRIORITY = {
    "adjudicated": 8,
    "human": 7,
    "formal": 6,
    "executable": 5,
    "symbolic": 4,
    "numeric": 3,
    "exact": 2,
    "llm": 1,
}


def _best_label(labels: Iterable[OutcomeLabel]) -> Optional[OutcomeLabel]:
    labels = list(labels)
    if not labels:
        return None
    return max(
        labels, key=lambda item: (_LABEL_PRIORITY.get(item.scorer_type.value, 0), item.created_at)
    )


def _evidence_source_map(episode: Episode) -> Dict[str, str]:
    observations = {item.observation_id: item for item in episode.source_observations}
    return {
        item.evidence_id: observations[item.observation_id].source_id
        for item in episode.evidence
        if item.observation_id in observations
    }


def resolved_source_labels(episode: Episode) -> Dict[str, LabelValue]:
    """Resolve the last produced evidence per source to its best available label."""

    source_map = _evidence_source_map(episode)
    labels_by_target: Dict[str, List[OutcomeLabel]] = {}
    for label in episode.labels:
        if label.target_type == "evidence":
            labels_by_target.setdefault(label.target_id, []).append(label)
    latest: Dict[str, Tuple[int, LabelValue]] = {}
    sequence = {item.evidence_id: item.sequence for item in episode.evidence}
    for evidence_id, source_id in source_map.items():
        label = _best_label(labels_by_target.get(evidence_id, []))
        if label is None:
            continue
        current = latest.get(source_id)
        candidate = (sequence.get(evidence_id, -1), label.value)
        if current is None or candidate[0] >= current[0]:
            latest[source_id] = candidate
    return {source_id: value for source_id, (_, value) in latest.items()}


def final_label(episode: Episode) -> Optional[LabelValue]:
    final_id = episode.final_output.evidence_id
    if final_id is None:
        return None
    label = _best_label(
        item
        for item in episode.labels
        if item.target_type == "evidence" and item.target_id == final_id
    )
    return None if label is None else label.value


def availability_profile(episodes: Iterable[Episode], source_id: str) -> Dict[str, Any]:
    episodes = list(episodes)
    observations = [
        item
        for episode in episodes
        for item in episode.source_observations
        if item.source_id == source_id
    ]
    opportunities = Counter(item.opportunity.value for item in observations)
    invocations = Counter(item.invocation.value for item in observations)
    outcomes = Counter(item.outcome.value for item in observations)
    labels = [resolved_source_labels(episode).get(source_id) for episode in episodes]
    correct = sum(value == LabelValue.correct for value in labels)
    incorrect = sum(value == LabelValue.incorrect for value in labels)
    binary = correct + incorrect
    produced = outcomes.get(ObservationOutcome.produced.value, 0)
    eligible_episodes = sum(
        any(
            item.source_id == source_id and item.opportunity.value == "eligible"
            for item in episode.source_observations
        )
        for episode in episodes
    )
    called_episodes = sum(
        any(
            item.source_id == source_id and item.invocation.value == "called"
            for item in episode.source_observations
        )
        for episode in episodes
    )
    produced_episodes = sum(
        any(
            item.source_id == source_id and item.outcome == ObservationOutcome.produced
            for item in episode.source_observations
        )
        for episode in episodes
    )
    registered = len(episodes)
    return {
        "source_id": source_id,
        "registered_episodes": len(episodes),
        "observations": len(observations),
        "opportunity": dict(sorted(opportunities.items())),
        "invocation": dict(sorted(invocations.items())),
        "outcome": dict(sorted(outcomes.items())),
        "produced": produced,
        "binary_scorable": binary,
        "correct": correct,
        "incorrect": incorrect,
        "episode_denominators": {
            "eligible": eligible_episodes,
            "called": called_episodes,
            "produced": produced_episodes,
        },
        "opportunity_rate": eligible_episodes / registered if registered else None,
        "call_rate_given_eligible": called_episodes / eligible_episodes
        if eligible_episodes
        else None,
        "production_rate_given_called": produced_episodes / called_episodes
        if called_episodes
        else None,
        "scorable_rate_given_produced": binary / produced_episodes if produced_episodes else None,
        "conditional_correctness": (correct / binary) if binary else None,
        "operational_support_rate": (correct / registered) if registered else None,
        "intervals_exact_95": {
            "opportunity_rate": list(clopper_pearson(eligible_episodes, registered)),
            "call_rate_given_eligible": list(clopper_pearson(called_episodes, eligible_episodes)),
            "production_rate_given_called": list(
                clopper_pearson(produced_episodes, called_episodes)
            ),
            "scorable_rate_given_produced": list(clopper_pearson(binary, produced_episodes)),
            "conditional_correctness": list(clopper_pearson(correct, binary)),
            "operational_support_rate": list(clopper_pearson(correct, registered)),
        },
        "episode_proportions_exact_95": {
            "eligible_over_registered": list(clopper_pearson(eligible_episodes, registered)),
            "called_over_registered": list(clopper_pearson(called_episodes, registered)),
            "produced_over_registered": list(clopper_pearson(produced_episodes, registered)),
            "scorable_over_registered": list(clopper_pearson(binary, registered)),
        },
    }


def final_outcome_profile(episodes: Iterable[Episode]) -> Dict[str, Any]:
    """Report survival and correctness without silently dropping empty finals."""

    episodes = list(episodes)
    produced = sum(episode.final_output.status.value == "produced" for episode in episodes)
    labels = [final_label(episode) for episode in episodes]
    correct = sum(value == LabelValue.correct for value in labels)
    incorrect = sum(value == LabelValue.incorrect for value in labels)
    binary = correct + incorrect
    registered = len(episodes)
    return {
        "registered_episodes": len(episodes),
        "produced_finals": produced,
        "binary_scorable_finals": binary,
        "correct_finals": correct,
        "incorrect_finals": incorrect,
        "survival_rate": produced / registered if registered else None,
        "conditional_accuracy": correct / binary if binary else None,
        "end_to_end_accuracy": correct / registered if registered else None,
        "intervals_exact_95": {
            "survival_rate": list(clopper_pearson(produced, registered)),
            "conditional_accuracy": list(clopper_pearson(correct, binary)),
            "end_to_end_accuracy": list(clopper_pearson(correct, registered)),
        },
    }


def _distribution(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "q1": None, "q3": None, "p90": None, "mean": None}
    array = np.asarray(values, dtype=float)
    return {
        "n": len(values),
        "median": float(np.median(array)),
        "q1": float(np.quantile(array, 0.25)),
        "q3": float(np.quantile(array, 0.75)),
        "p90": float(np.quantile(array, 0.90)),
        "mean": float(np.mean(array)),
    }


def cost_profile(episodes: Iterable[Episode], source_id: str) -> Dict[str, Any]:
    """Summarize per-episode measured cost for one declared source."""

    episodes = list(episodes)
    fields = (
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "tool_executions",
        "latency_s",
    )
    values: Dict[str, List[float]] = {field: [] for field in fields}
    for episode in episodes:
        observations = [item for item in episode.source_observations if item.source_id == source_id]
        for field in fields:
            measured = [getattr(item.cost, field) for item in observations]
            measured = [float(value) for value in measured if value is not None]
            if measured:
                values[field].append(sum(measured))
    return {
        "source_id": source_id,
        "registered_episodes": len(episodes),
        "metrics": {field: _distribution(values[field]) for field in fields},
        "compatibility_note": "Cost is comparable across systems only when instrumentation units and budget conditions match.",
    }


def _phi(cells: Tuple[int, int, int, int]) -> Optional[float]:
    both_correct, a_correct_b_wrong, a_wrong_b_correct, both_wrong = cells
    numerator = both_correct * both_wrong - a_correct_b_wrong * a_wrong_b_correct
    denominator = math.sqrt(
        (both_correct + a_correct_b_wrong)
        * (a_wrong_b_correct + both_wrong)
        * (both_correct + a_wrong_b_correct)
        * (a_correct_b_wrong + both_wrong)
    )
    return None if denominator == 0 else numerator / denominator


def _mutual_information(cells: Tuple[int, int, int, int]) -> Optional[float]:
    matrix = np.array([[cells[0], cells[1]], [cells[2], cells[3]]], dtype=float)
    total = matrix.sum()
    if total == 0:
        return None
    joint = matrix / total
    row = joint.sum(axis=1)
    column = joint.sum(axis=0)
    value = 0.0
    for i in range(2):
        for j in range(2):
            if joint[i, j] > 0 and row[i] > 0 and column[j] > 0:
                value += float(joint[i, j] * math.log(joint[i, j] / (row[i] * column[j])))
    return value


def _bootstrap_phi_summary(values: Sequence[float], *, requested: int) -> Dict[str, Any]:
    """Describe a percentile bootstrap without hiding undefined phi draws.

    Phi is undefined whenever either binary marginal has zero variance.  Small
    or sparse resamples can therefore yield no finite statistic even when the
    statistic is defined in the observed sample.  The percentile range below is
    explicitly conditional on the subset of resamples with defined phi; it is
    not presented as an unconditional coverage guarantee.
    """

    defined = len(values)
    undefined = max(requested - defined, 0)
    if requested <= 0:
        interval = [None, None]
        status = "not_requested"
        conditioning = None
        fraction = None
    elif not values:
        interval = [None, None]
        status = "unavailable_no_defined_replicates"
        conditioning = "defined_phi_replicates_only"
        fraction = 0.0
    else:
        low, high = np.quantile(values, [0.025, 0.975])
        interval = [float(low), float(high)]
        fraction = defined / requested
        if undefined:
            status = "conditional_on_defined_replicates"
            conditioning = "defined_phi_replicates_only"
        else:
            status = "all_replicates_defined"
            conditioning = "all_requested_replicates"
    return {
        "requested_replicates": requested,
        "defined_replicates": defined,
        "undefined_replicates": undefined,
        "defined_fraction": fraction,
        "percentile_range_defined_95": interval,
        "interval_status": status,
        "conditioning": conditioning,
        "quantiles": [0.025, 0.975],
        "nominal_coverage_established": False,
    }


def _bootstrap_phi(
    rows: Sequence[Tuple[bool, bool]], *, replicates: int, seed: int
) -> Dict[str, Any]:
    if len(rows) < 2 or replicates <= 0:
        return _bootstrap_phi_summary([], requested=replicates)
    rng = np.random.default_rng(seed)
    values: List[float] = []
    rows_array = np.asarray(rows, dtype=bool)
    for _ in range(replicates):
        sample = rows_array[rng.integers(0, len(rows_array), len(rows_array))]
        a_error = sample[:, 0]
        b_error = sample[:, 1]
        cells = (
            int(np.sum(~a_error & ~b_error)),
            int(np.sum(~a_error & b_error)),
            int(np.sum(a_error & ~b_error)),
            int(np.sum(a_error & b_error)),
        )
        value = _phi(cells)
        if value is not None:
            values.append(value)
    return _bootstrap_phi_summary(values, requested=replicates)


def pairwise_dependence(
    episodes: Iterable[Episode],
    source_a: str,
    source_b: str,
    *,
    bootstrap_replicates: int = 1000,
    seed: int = 20260822,
) -> Dict[str, Any]:
    rows: List[Tuple[bool, bool]] = []
    for episode in episodes:
        labels = resolved_source_labels(episode)
        a = labels.get(source_a)
        b = labels.get(source_b)
        if a in {LabelValue.correct, LabelValue.incorrect} and b in {
            LabelValue.correct,
            LabelValue.incorrect,
        }:
            rows.append((a == LabelValue.incorrect, b == LabelValue.incorrect))
    both_correct = sum(not a and not b for a, b in rows)
    a_correct_b_wrong = sum(not a and b for a, b in rows)
    a_wrong_b_correct = sum(a and not b for a, b in rows)
    both_wrong = sum(a and b for a, b in rows)
    cells = (both_correct, a_correct_b_wrong, a_wrong_b_correct, both_wrong)
    phi = _phi(cells)
    bootstrap = _bootstrap_phi(rows, replicates=bootstrap_replicates, seed=seed)
    corrected = [value + 0.5 for value in cells]
    odds_ratio = (corrected[0] * corrected[3]) / (corrected[1] * corrected[2])
    a_errors = a_wrong_b_correct + both_wrong
    b_errors = a_correct_b_wrong + both_wrong
    return {
        "source_a": source_a,
        "source_b": source_b,
        "complete_cases": len(rows),
        "cells": {
            "both_correct": both_correct,
            "a_correct_b_wrong": a_correct_b_wrong,
            "a_wrong_b_correct": a_wrong_b_correct,
            "both_wrong": both_wrong,
        },
        "phi": phi,
        "phi_bootstrap_95": bootstrap["percentile_range_defined_95"],
        "phi_bootstrap_summary": bootstrap,
        "joint_error_probability": (both_wrong / len(rows)) if rows else None,
        "p_b_wrong_given_a_wrong": (both_wrong / a_errors) if a_errors else None,
        "p_a_wrong_given_b_wrong": (both_wrong / b_errors) if b_errors else None,
        "odds_ratio_haldane": odds_ratio if rows else None,
        "mutual_information_nats": _mutual_information(cells),
    }


def _type_pair_cells(
    episode: Episode,
    source_type_a: SourceType,
    source_type_b: SourceType,
    provenance_relation: str,
) -> Tuple[int, int, int, int]:
    labels = resolved_source_labels(episode)
    source_types = {source.source_id: source.source_type for source in episode.sources}
    provenance_groups = {source.source_id: source.provenance_group for source in episode.sources}
    a_ids = sorted(
        source_id
        for source_id, value in labels.items()
        if source_types.get(source_id) == source_type_a
        and value in {LabelValue.correct, LabelValue.incorrect}
    )
    b_ids = sorted(
        source_id
        for source_id, value in labels.items()
        if source_types.get(source_id) == source_type_b
        and value in {LabelValue.correct, LabelValue.incorrect}
    )
    if source_type_a == source_type_b:
        pairs = [
            (a_ids[left], a_ids[right])
            for left in range(len(a_ids))
            for right in range(left + 1, len(a_ids))
        ]
    else:
        pairs = [(source_a, source_b) for source_a in a_ids for source_b in b_ids]
    if provenance_relation != "all":
        pairs = [
            (source_a, source_b)
            for source_a, source_b in pairs
            if (provenance_groups.get(source_a) == provenance_groups.get(source_b))
            == (provenance_relation == "same")
        ]
    cells = [0, 0, 0, 0]
    for source_a, source_b in pairs:
        a_wrong = labels[source_a] == LabelValue.incorrect
        b_wrong = labels[source_b] == LabelValue.incorrect
        if not a_wrong and not b_wrong:
            cells[0] += 1
        elif not a_wrong and b_wrong:
            cells[1] += 1
        elif a_wrong and not b_wrong:
            cells[2] += 1
        else:
            cells[3] += 1
    return tuple(cells)  # type: ignore[return-value]


def _cluster_bootstrap_episode_balanced_phi(
    episode_cells: Sequence[Tuple[int, int, int, int]],
    *,
    replicates: int,
    seed: int,
) -> Dict[str, Any]:
    if len(episode_cells) < 2 or replicates <= 0:
        return _bootstrap_phi_summary([], requested=replicates)
    proportions = np.asarray(
        [np.asarray(cells, dtype=float) / sum(cells) for cells in episode_cells],
        dtype=float,
    )
    rng = np.random.default_rng(seed)
    values: List[float] = []
    for _ in range(replicates):
        sample = proportions[rng.integers(0, len(proportions), len(proportions))]
        value = _phi(tuple(float(item) for item in sample.mean(axis=0)))
        if value is not None:
            values.append(value)
    return _bootstrap_phi_summary(values, requested=replicates)


def source_type_dependence(
    episodes: Iterable[Episode],
    source_type_a: SourceType,
    source_type_b: SourceType,
    *,
    bootstrap_replicates: int = 1000,
    seed: int = 20260822,
    provenance_relation: str = "all",
) -> Dict[str, Any]:
    """Estimate type-pair dependence with equal episode weight and cluster bootstrap.

    Each episode contributes its within-episode pair-cell proportions once,
    preventing systems with more candidate agents from dominating the primary
    estimate. Raw pair-weighted cells are retained as a sensitivity summary.
    """

    if provenance_relation not in {"all", "same", "different"}:
        raise ValueError("provenance_relation must be all, same or different")
    episodes = list(episodes)
    episode_cells = [
        cells
        for episode in episodes
        if sum(
            cells := _type_pair_cells(
                episode,
                source_type_a,
                source_type_b,
                provenance_relation,
            )
        )
        > 0
    ]
    pooled = tuple(sum(cells[index] for cells in episode_cells) for index in range(4))
    balanced = (
        tuple(
            float(value)
            for value in np.mean(
                [np.asarray(cells, dtype=float) / sum(cells) for cells in episode_cells],
                axis=0,
            )
        )
        if episode_cells
        else None
    )
    bootstrap = _cluster_bootstrap_episode_balanced_phi(
        episode_cells, replicates=bootstrap_replicates, seed=seed
    )
    return {
        "source_type_a": source_type_a.value,
        "source_type_b": source_type_b.value,
        "provenance_relation": provenance_relation,
        "registered_episodes": len(episodes),
        "episodes_with_pairs": len(episode_cells),
        "pair_observations": sum(sum(cells) for cells in episode_cells),
        "episode_balanced_cells": (
            {
                "both_correct": balanced[0],
                "a_correct_b_wrong": balanced[1],
                "a_wrong_b_correct": balanced[2],
                "both_wrong": balanced[3],
            }
            if balanced is not None
            else None
        ),
        "pooled_pair_cells": {
            "both_correct": pooled[0],
            "a_correct_b_wrong": pooled[1],
            "a_wrong_b_correct": pooled[2],
            "both_wrong": pooled[3],
        },
        "phi_episode_balanced": _phi(balanced) if balanced is not None else None,
        "phi_cluster_bootstrap_95": bootstrap["percentile_range_defined_95"],
        "phi_cluster_bootstrap_summary": bootstrap,
        "phi_pair_weighted_sensitivity": _phi(pooled),
        "joint_error_probability_episode_balanced": (balanced[3] if balanced is not None else None),
        "unit_of_inference": "episode",
        "pair_weighting_is_primary": False,
    }


def _latest_evidence_by_source(episode: Episode, source_id: str) -> Optional[Any]:
    source_map = _evidence_source_map(episode)
    candidates = [
        evidence
        for evidence in episode.evidence
        if source_map.get(evidence.evidence_id) == source_id
    ]
    return max(candidates, key=lambda item: item.sequence) if candidates else None


def _normalized_whitespace(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    result = " ".join(value.split())
    return result or None


def text_repetition_profile(
    episodes: Iterable[Episode], source_a: str, source_b: str
) -> Dict[str, Any]:
    """Measure exact content repetition separately from answer equivalence."""

    episodes = list(episodes)
    counts = Counter()
    for episode in episodes:
        evidence_a = _latest_evidence_by_source(episode, source_a)
        evidence_b = _latest_evidence_by_source(episode, source_b)
        if evidence_a is None or evidence_b is None:
            continue
        counts["both_evidence_present"] += 1
        if evidence_a.content.content_hash == evidence_b.content.content_hash:
            counts["identical_content_hash"] += 1
        text_a = _normalized_whitespace(evidence_a.content.text)
        text_b = _normalized_whitespace(evidence_b.content.text)
        if text_a is not None and text_b is not None:
            counts["text_comparable"] += 1
            if text_a == text_b:
                counts["exact_text_repeat"] += 1
        answer_a = _normalized_whitespace(evidence_a.content.normalized_answer)
        answer_b = _normalized_whitespace(evidence_b.content.normalized_answer)
        if answer_a is not None and answer_b is not None:
            counts["answer_comparable"] += 1
            if answer_a == answer_b:
                counts["exact_normalized_answer_repeat"] += 1
    evidence_denominator = counts["both_evidence_present"]
    text_denominator = counts["text_comparable"]
    answer_denominator = counts["answer_comparable"]
    return {
        "source_a": source_a,
        "source_b": source_b,
        "registered_episodes": len(episodes),
        "counts": dict(counts),
        "identical_content_hash_rate": (
            counts["identical_content_hash"] / evidence_denominator
            if evidence_denominator
            else None
        ),
        "exact_text_repeat_rate": (
            counts["exact_text_repeat"] / text_denominator if text_denominator else None
        ),
        "exact_normalized_answer_repeat_rate": (
            counts["exact_normalized_answer_repeat"] / answer_denominator
            if answer_denominator
            else None
        ),
        "intervals_exact_95": {
            "identical_content_hash_rate": list(
                clopper_pearson(counts["identical_content_hash"], evidence_denominator)
            ),
            "exact_text_repeat_rate": list(
                clopper_pearson(counts["exact_text_repeat"], text_denominator)
            ),
            "exact_normalized_answer_repeat_rate": list(
                clopper_pearson(counts["exact_normalized_answer_repeat"], answer_denominator)
            ),
        },
        "semantic_equivalence_inferred": False,
    }


def clopper_pearson(
    successes: int, trials: int, alpha: float = 0.05
) -> Tuple[Optional[float], Optional[float]]:
    if trials <= 0:
        return None, None
    low = (
        0.0
        if successes == 0
        else float(beta_distribution.ppf(alpha / 2, successes, trials - successes + 1))
    )
    high = (
        1.0
        if successes == trials
        else float(beta_distribution.ppf(1 - alpha / 2, successes + 1, trials - successes))
    )
    return low, high


def cofailure(episodes: Iterable[Episode], source_ids: Sequence[str]) -> Dict[str, Any]:
    episodes = list(episodes)
    complete = 0
    complete_all_wrong = 0
    operational_no_correct = 0
    for episode in episodes:
        labels = resolved_source_labels(episode)
        values = [labels.get(source_id) for source_id in source_ids]
        binary = all(value in {LabelValue.correct, LabelValue.incorrect} for value in values)
        if binary:
            complete += 1
            complete_all_wrong += int(all(value == LabelValue.incorrect for value in values))
        operational_no_correct += int(not any(value == LabelValue.correct for value in values))
    low, high = clopper_pearson(complete_all_wrong, complete)
    return {
        "source_ids": list(source_ids),
        "registered_episodes": len(episodes),
        "complete_cases": complete,
        "complete_all_wrong": complete_all_wrong,
        "complete_case_beta": (complete_all_wrong / complete) if complete else None,
        "complete_case_beta_exact_95": [low, high],
        "operational_no_correct_support": operational_no_correct,
        "operational_no_correct_support_rate": (operational_no_correct / len(episodes))
        if episodes
        else None,
    }


def provenance_support(episode: Episode, *, include_composite: bool = False) -> Dict[str, Any]:
    """Count correct upstream support without double-counting provenance groups."""

    labels = resolved_source_labels(episode)
    sources = {item.source_id: item for item in episode.sources}
    correct_sources = sorted(
        source_id
        for source_id, value in labels.items()
        if value == LabelValue.correct
        and source_id in sources
        and (include_composite or sources[source_id].source_type != SourceType.composite)
    )
    groups = sorted(
        {
            sources[source_id].provenance_group
            for source_id in correct_sources
            if source_id in sources
        }
    )
    return {
        "episode_id": episode.episode_id,
        "nominal_correct_sources": len(correct_sources),
        "correct_source_ids": correct_sources,
        "distinct_provenance_groups": len(groups),
        "provenance_groups": groups,
    }


def transition_metrics(episodes: Iterable[Episode], upstream: str, checker: str) -> Dict[str, Any]:
    counts = Counter()
    for episode in episodes:
        labels = resolved_source_labels(episode)
        a = labels.get(upstream)
        b = labels.get(checker)
        final = final_label(episode)
        if a not in {LabelValue.correct, LabelValue.incorrect} or b not in {
            LabelValue.correct,
            LabelValue.incorrect,
        }:
            continue
        if a == LabelValue.incorrect:
            counts["upstream_wrong_checker_scorable"] += 1
            if b == LabelValue.correct:
                counts["repair_opportunity"] += 1
                if final == LabelValue.correct:
                    counts["repair_realized"] += 1
        else:
            counts["upstream_correct_checker_scorable"] += 1
            if b == LabelValue.incorrect:
                counts["harm_opportunity"] += 1
                if final == LabelValue.incorrect:
                    counts["harm_realized"] += 1
    repair_denominator = counts["upstream_wrong_checker_scorable"]
    harm_denominator = counts["upstream_correct_checker_scorable"]
    repair_opportunity = counts["repair_opportunity"]
    harm_opportunity = counts["harm_opportunity"]
    return {
        "upstream": upstream,
        "checker": checker,
        "counts": dict(counts),
        "repair_opportunity_rate": counts["repair_opportunity"] / repair_denominator
        if repair_denominator
        else None,
        "repair_realization_rate": counts["repair_realized"] / repair_opportunity
        if repair_opportunity
        else None,
        "harm_opportunity_rate": counts["harm_opportunity"] / harm_denominator
        if harm_denominator
        else None,
        "harm_realization_rate": counts["harm_realized"] / harm_opportunity
        if harm_opportunity
        else None,
        "intervals_exact_95": {
            "repair_opportunity_rate": list(
                clopper_pearson(counts["repair_opportunity"], repair_denominator)
            ),
            "repair_realization_rate": list(
                clopper_pearson(counts["repair_realized"], repair_opportunity)
            ),
            "harm_opportunity_rate": list(
                clopper_pearson(counts["harm_opportunity"], harm_denominator)
            ),
            "harm_realization_rate": list(
                clopper_pearson(counts["harm_realized"], harm_opportunity)
            ),
        },
        "causal_interpretation": False,
    }


def _comparison_text(episode: Episode, evidence_id: str) -> Optional[str]:
    evidence = next((item for item in episode.evidence if item.evidence_id == evidence_id), None)
    if evidence is None:
        return None
    value = evidence.content.normalized_answer or evidence.content.text
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def conflict_adoption(episodes: Iterable[Episode], upstream: str, checker: str) -> Dict[str, Any]:
    """Measure direct decision selection and a separately labelled text-match proxy."""

    counts = Counter()
    for episode in episodes:
        labels = resolved_source_labels(episode)
        a = labels.get(upstream)
        b = labels.get(checker)
        if a not in {LabelValue.correct, LabelValue.incorrect} or b not in {
            LabelValue.correct,
            LabelValue.incorrect,
        }:
            continue
        if a == b:
            continue
        counts["binary_disagreements"] += 1
        source_map = _evidence_source_map(episode)

        direct = None
        for decision in sorted(episode.decisions, key=lambda item: item.sequence, reverse=True):
            candidates = set(decision.candidate_evidence_ids or decision.input_evidence_ids)
            candidate_sources = {source_map.get(item) for item in candidates}
            if upstream not in candidate_sources or checker not in candidate_sources:
                continue
            if decision.selected_evidence_ids:
                direct = decision
                break
        if direct is not None:
            counts["directly_observable"] += 1
            selected_sources = {
                source_map.get(item) for item in direct.selected_evidence_ids if item in source_map
            }
            if checker in selected_sources:
                counts["checker_selected"] += 1
                if b == LabelValue.correct:
                    counts["correct_checker_selected"] += 1
                else:
                    counts["wrong_checker_selected"] += 1
        else:
            counts["selection_not_observable"] += 1

        checker_evidence = [
            item for item in episode.evidence if source_map.get(item.evidence_id) == checker
        ]
        if episode.final_output.evidence_id and checker_evidence:
            checker_latest = max(checker_evidence, key=lambda item: item.sequence)
            checker_text = _comparison_text(episode, checker_latest.evidence_id)
            final_text = _comparison_text(episode, episode.final_output.evidence_id)
            if checker_text is not None and final_text is not None:
                counts["proxy_comparable"] += 1
                if checker_text == final_text:
                    counts["proxy_final_exactly_matches_checker"] += 1

    direct_denominator = counts["directly_observable"]
    proxy_denominator = counts["proxy_comparable"]
    return {
        "upstream": upstream,
        "checker": checker,
        "counts": dict(counts),
        "direct_checker_adoption_rate": (
            counts["checker_selected"] / direct_denominator if direct_denominator else None
        ),
        "proxy_final_exact_match_rate": (
            counts["proxy_final_exactly_matches_checker"] / proxy_denominator
            if proxy_denominator
            else None
        ),
        "intervals_exact_95": {
            "direct_checker_adoption_rate": list(
                clopper_pearson(counts["checker_selected"], direct_denominator)
            ),
            "proxy_final_exact_match_rate": list(
                clopper_pearson(counts["proxy_final_exactly_matches_checker"], proxy_denominator)
            ),
        },
        "proxy_is_direct_utilization": False,
        "causal_interpretation": False,
    }


def effective_support_equicorrelated(k: int, rho: float) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    lower = -1 / (k - 1) if k > 1 else -1.0
    if rho <= lower or rho > 1:
        raise ValueError("rho is outside the positive-semidefinite equicorrelation range")
    return k / (1 + (k - 1) * rho)
