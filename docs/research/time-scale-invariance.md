# Time-scale invariance

Phase 1 Step 4 prepares time-scale comparable representations by resampling normalized channels to fixed point counts such as 16, 32, 64, 128, and 256.

This does not implement similarity search. Tests only verify preparation properties: endpoint preservation, determinism, monotonic-path preservation, and stretched linear-path equivalence after resampling.

