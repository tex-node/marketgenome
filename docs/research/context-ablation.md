# Context ablation

Context ablation evaluates whether transparent market context improves or hurts analogue retrieval. The registered `context_ablation_v1` experiment compares full analogue retrieval against baselines such as DNA-only cosine, raw shape, and context-filtered random history.

Phase 1 uses persisted `MarketContext` states and distributions; it does not learn context weights.

