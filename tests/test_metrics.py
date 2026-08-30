# SPDX-License-Identifier: MIT

import math
import random

from mathaudit.metrics import (
    availability_profile,
    cofailure,
    conflict_adoption,
    effective_support_equicorrelated,
    final_outcome_profile,
    pairwise_dependence,
    provenance_support,
    source_type_dependence,
    text_repetition_profile,
    transition_metrics,
)
from mathaudit.models import (
    Decision,
    DecisionStatus,
    DecisionType,
    LabelValue,
    ObservationOutcome,
    SourceType,
)


def test_balanced_independence_oracle(episode_factory):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, True, False, True),
        episode_factory(2, False, True, True),
        episode_factory(3, False, False, False),
    ]
    result = pairwise_dependence(episodes, "a", "b", bootstrap_replicates=0)
    assert result["cells"] == {
        "both_correct": 1,
        "a_correct_b_wrong": 1,
        "a_wrong_b_correct": 1,
        "both_wrong": 1,
    }
    assert result["phi"] == 0
    assert result["joint_error_probability"] == 0.25
    assert result["mutual_information_nats"] == 0


def test_source_type_dependence_is_episode_balanced_and_clustered(episode_factory):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, True, False, True),
        episode_factory(2, False, True, True),
        episode_factory(3, False, False, False),
    ]
    result = source_type_dependence(
        episodes,
        SourceType.llm,
        SourceType.python,
        bootstrap_replicates=20,
        seed=7,
    )
    assert result["episodes_with_pairs"] == 4
    assert result["pair_observations"] == 4
    assert result["episode_balanced_cells"] == {
        "both_correct": 0.25,
        "a_correct_b_wrong": 0.25,
        "a_wrong_b_correct": 0.25,
        "both_wrong": 0.25,
    }
    assert result["phi_episode_balanced"] == 0
    assert result["unit_of_inference"] == "episode"
    assert result["provenance_relation"] == "all"


def test_source_type_dependence_filters_provenance_relation(episode_factory):
    episodes = [
        episode_factory(0, True, True, True, group_a="shared", group_b="shared"),
        episode_factory(1, False, False, False, group_a="shared", group_b="shared"),
        episode_factory(2, True, False, True, group_a="left", group_b="right"),
        episode_factory(3, False, True, True, group_a="left", group_b="right"),
    ]
    same = source_type_dependence(
        episodes,
        SourceType.llm,
        SourceType.python,
        bootstrap_replicates=0,
        provenance_relation="same",
    )
    different = source_type_dependence(
        episodes,
        SourceType.llm,
        SourceType.python,
        bootstrap_replicates=0,
        provenance_relation="different",
    )
    assert same["episodes_with_pairs"] == 2
    assert same["phi_episode_balanced"] == 1
    assert different["episodes_with_pairs"] == 2
    assert different["phi_episode_balanced"] == -1


def _add_second_llm(episode, value):
    source = episode.sources[0].model_copy(update={"source_id": "a2"})
    observation = episode.source_observations[0].model_copy(
        update={"observation_id": "obs:a2:%s" % episode.episode_id, "source_id": "a2"}
    )
    evidence = episode.evidence[0].model_copy(
        update={
            "evidence_id": "ev:a2:%s" % episode.episode_id,
            "observation_id": observation.observation_id,
            "sequence": 4,
        }
    )
    label = episode.labels[0].model_copy(
        update={
            "label_id": "label:a2:%s" % episode.episode_id,
            "target_id": evidence.evidence_id,
            "value": LabelValue.correct if value else LabelValue.incorrect,
        }
    )
    return episode.model_copy(
        update={
            "sources": [*episode.sources, source],
            "source_observations": [*episode.source_observations, observation],
            "evidence": [*episode.evidence, evidence],
            "labels": [*episode.labels, label],
        }
    )


def test_source_type_dependence_supports_multiple_same_type_sources(episode_factory):
    episodes = [
        _add_second_llm(episode_factory(0, True, True, True), True),
        _add_second_llm(episode_factory(1, True, True, True), False),
        _add_second_llm(episode_factory(2, False, True, True), True),
        _add_second_llm(episode_factory(3, False, True, False), False),
    ]
    result = source_type_dependence(
        episodes, SourceType.llm, SourceType.llm, bootstrap_replicates=0
    )
    assert result["episodes_with_pairs"] == 4
    assert result["pair_observations"] == 4
    assert result["phi_episode_balanced"] == 0


def test_text_repetition_distinguishes_full_text_from_answer_fields(episode_factory):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, True, False, True),
        episode_factory(2, False, True, True),
        episode_factory(3, False, False, False),
    ]
    result = text_repetition_profile(episodes, "a", "b")
    assert result["counts"]["text_comparable"] == 4
    assert result["counts"]["exact_text_repeat"] == 2
    assert result["exact_text_repeat_rate"] == 0.5
    assert result["exact_normalized_answer_repeat_rate"] is None
    assert result["semantic_equivalence_inferred"] is False


def test_perfect_positive_and_negative_dependence(episode_factory):
    positive = [
        episode_factory(0, True, True, True),
        episode_factory(1, True, True, True),
        episode_factory(2, False, False, False),
        episode_factory(3, False, False, False),
    ]
    negative = [
        episode_factory(4, True, False, True),
        episode_factory(5, True, False, True),
        episode_factory(6, False, True, True),
        episode_factory(7, False, True, True),
    ]
    assert pairwise_dependence(positive, "a", "b", bootstrap_replicates=0)["phi"] == 1
    assert pairwise_dependence(negative, "a", "b", bootstrap_replicates=0)["phi"] == -1


def test_source_order_permutation_invariance(episode_factory):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, True, False, True),
        episode_factory(2, False, True, True),
        episode_factory(3, False, False, False),
    ]
    forward = pairwise_dependence(episodes, "a", "b", bootstrap_replicates=100, seed=4)
    reverse = pairwise_dependence(episodes, "b", "a", bootstrap_replicates=100, seed=4)
    assert forward["phi"] == reverse["phi"]
    assert forward["joint_error_probability"] == reverse["joint_error_probability"]


def test_bootstrap_is_reproducible(episode_factory):
    episodes = [episode_factory(i, i % 3 != 0, i % 4 != 0, True) for i in range(20)]
    first = pairwise_dependence(episodes, "a", "b", bootstrap_replicates=200, seed=17)
    second = pairwise_dependence(episodes, "a", "b", bootstrap_replicates=200, seed=17)
    assert first["phi_bootstrap_95"] == second["phi_bootstrap_95"]


def test_cofailure_reports_complete_and_operational_rates(episode_factory):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, False, False, False),
    ]
    result = cofailure(episodes, ["a", "b"])
    assert result["complete_case_beta"] == 0.5
    assert result["operational_no_correct_support_rate"] == 0.5


def test_fix_harm_oracle(episode_factory):
    episodes = [
        episode_factory(0, False, True, True),
        episode_factory(1, False, True, False),
        episode_factory(2, False, False, False),
        episode_factory(3, True, False, False),
        episode_factory(4, True, False, True),
        episode_factory(5, True, True, True),
    ]
    result = transition_metrics(episodes, "a", "b")
    assert math.isclose(result["repair_opportunity_rate"], 2 / 3)
    assert result["repair_realization_rate"] == 0.5
    assert math.isclose(result["harm_opportunity_rate"], 2 / 3)
    assert result["harm_realization_rate"] == 0.5
    assert result["causal_interpretation"] is False


def test_duplicate_provenance_does_not_increase_distinct_support(episode_factory):
    episode = episode_factory(0, True, True, True, group_a="shared", group_b="shared")
    result = provenance_support(episode)
    assert result["nominal_correct_sources"] == 2
    assert result["distinct_provenance_groups"] == 1


def test_effective_support_is_model_based_formula():
    assert effective_support_equicorrelated(2, 0.0) == 2
    assert math.isclose(effective_support_equicorrelated(2, 0.5), 4 / 3)


def test_availability_and_final_profiles_use_registered_denominators(episode_factory):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, False, True, False),
    ]
    availability = availability_profile(episodes, "a")
    final = final_outcome_profile(episodes)
    assert availability["opportunity_rate"] == 1
    assert availability["production_rate_given_called"] == 1
    assert availability["operational_support_rate"] == 0.5
    assert final["survival_rate"] == 1
    assert final["conditional_accuracy"] == 0.5
    assert final["end_to_end_accuracy"] == 0.5


def test_conflict_adoption_separates_direct_selection_from_proxy(episode_factory):
    episode = episode_factory(0, False, True, True)
    episode = episode.model_copy(
        update={
            "decisions": [
                Decision(
                    decision_id="decision:select",
                    decision_type=DecisionType.selection,
                    stage="selection",
                    sequence=3,
                    status=DecisionStatus.completed,
                    input_evidence_ids=["ev:a:0", "ev:b:0"],
                    candidate_evidence_ids=["ev:a:0", "ev:b:0"],
                    selected_evidence_ids=["ev:b:0"],
                    output_evidence_ids=[],
                    policy="synthetic",
                )
            ]
        }
    )
    result = conflict_adoption([episode], "a", "b")
    assert result["counts"]["binary_disagreements"] == 1
    assert result["direct_checker_adoption_rate"] == 1
    assert result["proxy_final_exact_match_rate"] == 1
    assert result["proxy_is_direct_utilization"] is False


def test_randomized_phi_matches_contingency_formula(episode_factory):
    rng = random.Random(20260823)
    for batch in range(20):
        rows = [(bool(rng.getrandbits(1)), bool(rng.getrandbits(1))) for _ in range(24)]
        episodes = [
            episode_factory(batch * 24 + index, not a_error, not b_error, True)
            for index, (a_error, b_error) in enumerate(rows)
        ]
        result = pairwise_dependence(episodes, "a", "b", bootstrap_replicates=0)
        cc = sum(not a and not b for a, b in rows)
        cw = sum(not a and b for a, b in rows)
        wc = sum(a and not b for a, b in rows)
        ww = sum(a and b for a, b in rows)
        denominator = math.sqrt((cc + cw) * (wc + ww) * (cc + wc) * (cw + ww))
        expected = None if denominator == 0 else (cc * ww - cw * wc) / denominator
        if expected is None:
            assert result["phi"] is None
        else:
            assert math.isclose(result["phi"], expected)


def test_no_vote_is_excluded_not_counted_as_wrong(episode_factory):
    complete = episode_factory(0, True, False, True)
    missing = episode_factory(1, True, False, True)
    missing = missing.model_copy(
        update={
            "source_observations": [
                item.model_copy(update={"outcome": ObservationOutcome.no_vote})
                if item.source_id == "b"
                else item
                for item in missing.source_observations
            ],
            "evidence": [item for item in missing.evidence if item.evidence_id != "ev:b:1"],
            "labels": [item for item in missing.labels if item.target_id != "ev:b:1"],
        }
    )
    result = pairwise_dependence([complete, missing], "a", "b", bootstrap_replicates=0)
    assert result["complete_cases"] == 1
    assert result["cells"]["a_correct_b_wrong"] == 1
