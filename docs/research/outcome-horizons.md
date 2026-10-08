# Outcome Horizons

`forward_outcomes_v1` defines default horizons of 1, 3, 5, 10, 20, 40, 60, and 80 bars.

Horizons are expressed in bar counts so the same engine works across timeframes. A 10-bar outcome on H1 and a 10-bar outcome on M5 are comparable as sequence lengths, not elapsed-clock horizons.

Builds can request a subset of horizons through the API, CLI, or service layer.
