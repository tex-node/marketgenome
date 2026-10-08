# Experiment decisions

Experiment decisions are conservative labels:

- `INSUFFICIENT_DATA`: too few query evaluations;
- `NO_SUPPORTED_EDGE`: skill or direction accuracy does not clear basic thresholds;
- `PROMISING`: positive preliminary evidence, but not enough supported out-of-sample confidence;
- `OUT_OF_SAMPLE_SUPPORTED`: larger-sample positive result with confidence interval above zero.

These are research labels, not trading recommendations.

Diagnostic decisions added in Step 10A:

- `REPRESENTATION_FAILURE`
- `DISTANCE_FUNCTION_FAILURE`
- `CONTEXT_MISMATCH`
- `EPISODE_CONCENTRATION_FAILURE`
- `INSUFFICIENT_SAMPLE`
- `OUTCOME_HETEROGENEITY`
- `SCALE_HORIZON_MISMATCH`
- `SYNTHETIC_RECOVERY_ONLY`
- `REFINEMENT_PROMISING`
- `NO_RETRIEVAL_EDGE`

Study decisions added in Step 10A.1:

- `STUDY_NOT_READY`
- `PILOT_ONLY`
- `INSUFFICIENT_EPISODE_DIVERSITY`
- `REFINEMENT_PROMISING`
- `NO_RETRIEVAL_EDGE`

Study decisions are also research labels. A synthetic benchmark can prove plumbing and guardrails, but it is not real-market evidence.
