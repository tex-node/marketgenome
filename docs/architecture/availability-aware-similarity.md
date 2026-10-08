# Availability-aware similarity

Availability-aware distances compare only features available for both records and report coverage:

- joint feature count;
- joint feature ratio;
- group coverage;
- coverage rejection or penalty flags.

Policies:

- `joint_available_only_v1`;
- `joint_available_with_coverage_penalty_v1`;
- `minimum_coverage_reject_v1`;
- `group_balanced_availability_v1`.

New refined similarity methods use these diagnostics so missing features cannot silently create artificially high similarity.

