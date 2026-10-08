from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SimilarityMethodDefinition:
    code: str
    version: str
    label: str
    description: str
    input_sources: list[str]
    output_distance: str
    supports_missing_features: bool
    uses_future_outcomes: bool
    default_configuration: dict[str, Any]


SHAPE_EUCLIDEAN_V1 = SimilarityMethodDefinition(
    code="shape_euclidean_v1",
    version="similarity_v1",
    label="Shape Euclidean v1",
    description="Euclidean distance between normalized close paths.",
    input_sources=["normalized_pattern.close"],
    output_distance="lower_is_more_similar",
    supports_missing_features=False,
    uses_future_outcomes=False,
    default_configuration={"shape_weight": 1.0},
)

SHAPE_CORRELATION_V1 = SimilarityMethodDefinition(
    code="shape_correlation_v1",
    version="similarity_v1",
    label="Shape Correlation v1",
    description="Correlation distance between normalized close paths.",
    input_sources=["normalized_pattern.close"],
    output_distance="1_minus_correlation",
    supports_missing_features=False,
    uses_future_outcomes=False,
    default_configuration={"shape_weight": 1.0},
)

DNA_COSINE_V1 = SimilarityMethodDefinition(
    code="dna_cosine_v1",
    version="similarity_v1",
    label="Market DNA Cosine v1",
    description="Cosine distance between available Market DNA feature vectors.",
    input_sources=["market_dna.feature_vector"],
    output_distance="1_minus_cosine_similarity",
    supports_missing_features=True,
    uses_future_outcomes=False,
    default_configuration={"dna_weight": 1.0, "minimum_common_features": 8},
)

MARKET_ANALOGUE_V1 = SimilarityMethodDefinition(
    code="market_analogue_v1",
    version="similarity_v1",
    label="Market Analogue v1",
    description="Weighted blend of normalized path distance, DNA cosine distance, and context compatibility.",
    input_sources=["normalized_pattern.close", "market_dna.feature_vector", "market_context"],
    output_distance="weighted_distance",
    supports_missing_features=True,
    uses_future_outcomes=False,
    default_configuration={
        "shape_weight": 0.45,
        "dna_weight": 0.45,
        "context_weight": 0.10,
        "minimum_common_features": 8,
        "context_bonus": 0.0,
    },
)

DNA_ROBUST_COSINE_V1 = SimilarityMethodDefinition(
    code="dna_robust_cosine_v1",
    version="similarity_v2",
    label="Market DNA Robust Cosine v1",
    description="Cosine distance after transparent signed-log robust compression and availability coverage penalty.",
    input_sources=["market_dna.feature_vector"],
    output_distance="1_minus_cosine_similarity_with_coverage_penalty",
    supports_missing_features=True,
    uses_future_outcomes=False,
    default_configuration={
        "availability_policy": "joint_available_with_coverage_penalty_v1",
        "minimum_joint_feature_ratio": 0.70,
    },
)

DNA_ROBUST_EUCLIDEAN_V1 = SimilarityMethodDefinition(
    code="dna_robust_euclidean_v1",
    version="similarity_v2",
    label="Market DNA Robust Euclidean v1",
    description="Euclidean distance after transparent signed-log robust compression and availability coverage penalty.",
    input_sources=["market_dna.feature_vector"],
    output_distance="euclidean_with_coverage_penalty",
    supports_missing_features=True,
    uses_future_outcomes=False,
    default_configuration={
        "availability_policy": "joint_available_with_coverage_penalty_v1",
        "minimum_joint_feature_ratio": 0.70,
    },
)

DNA_GROUP_BALANCED_V1 = SimilarityMethodDefinition(
    code="dna_group_balanced_v1",
    version="similarity_v2",
    label="Market DNA Group-Balanced v1",
    description="Availability-aware DNA distance with equalized feature-group contribution.",
    input_sources=["market_dna.feature_vector"],
    output_distance="group_balanced_coverage_penalized_distance",
    supports_missing_features=True,
    uses_future_outcomes=False,
    default_configuration={
        "availability_policy": "group_balanced_availability_v1",
        "minimum_joint_feature_ratio": 0.70,
    },
)

SHAPE_DNA_CONTEXT_V2 = SimilarityMethodDefinition(
    code="shape_dna_context_v2",
    version="similarity_v2",
    label="Shape DNA Context v2",
    description="Transparent refined blend of shape, availability-aware robust DNA, and context compatibility.",
    input_sources=["normalized_pattern.close", "market_dna.feature_vector", "market_context"],
    output_distance="weighted_refined_distance",
    supports_missing_features=True,
    uses_future_outcomes=False,
    default_configuration={
        "shape_weight": 0.34,
        "dna_weight": 0.33,
        "context_weight": 0.33,
        "availability_policy": "joint_available_with_coverage_penalty_v1",
        "minimum_joint_feature_ratio": 0.70,
    },
)

EPISODE_DIVERSE_ANALOGUE_V1 = SimilarityMethodDefinition(
    code="episode_diverse_analogue_v1",
    version="similarity_v2",
    label="Episode Diverse Analogue v1",
    description="Study-level wrapper that ranks by an underlying transparent similarity and applies episode caps.",
    input_sources=["normalized_pattern.close", "market_dna.feature_vector", "market_context", "study_episode_assignments"],
    output_distance="episode_adjusted_weighted_distance",
    supports_missing_features=True,
    uses_future_outcomes=False,
    default_configuration={
        "underlying_similarity_method": "shape_dna_context_v2",
        "episode_definition": "temporal_episode_v1",
        "episode_cap": 1,
    },
)

SIMILARITY_METHODS = {
    item.code: item
    for item in (
        SHAPE_EUCLIDEAN_V1,
        SHAPE_CORRELATION_V1,
        DNA_COSINE_V1,
        MARKET_ANALOGUE_V1,
        DNA_ROBUST_COSINE_V1,
        DNA_ROBUST_EUCLIDEAN_V1,
        DNA_GROUP_BALANCED_V1,
        SHAPE_DNA_CONTEXT_V2,
        EPISODE_DIVERSE_ANALOGUE_V1,
    )
}


def list_similarity_methods() -> list[SimilarityMethodDefinition]:
    return list(SIMILARITY_METHODS.values())


def get_similarity_method(code: str) -> SimilarityMethodDefinition:
    try:
        return SIMILARITY_METHODS[code]
    except KeyError as exc:
        raise ValueError("SIMILARITY_METHOD_NOT_FOUND") from exc
