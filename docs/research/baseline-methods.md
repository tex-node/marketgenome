# Baseline methods

Step 9 registers explicit baseline methods so analogue retrieval is never evaluated in isolation.

Implemented baseline families:

- random historical;
- same-instrument random;
- same-context random;
- same-volatility random;
- recent-return match;
- raw-shape Euclidean;
- DNA-only cosine;
- context-filter random;
- unconditional historical outcome;
- naive continuation;
- naive mean reversion;
- recent mean return.

The AR baseline remains optional for Phase 1 and is not implemented.

