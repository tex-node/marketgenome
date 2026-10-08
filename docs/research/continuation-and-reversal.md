# Continuation and Reversal

Continuation/reversal classification compares the source window endpoint return with the future horizon return.

- Same sign: `CONTINUATION`.
- Opposite sign: `REVERSAL`.
- Future return inside tolerance: `SIDEWAYS`.
- Source movement too small: `SOURCE_DIRECTION_UNAVAILABLE`.

The source direction is calculated from the source window close-to-close endpoint and is verified against the immutable source window hash before outcome creation.
