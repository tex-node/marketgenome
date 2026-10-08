# Activity and shock context

Activity uses volume features only. Missing or unavailable volume produces `UNAVAILABLE`; price volatility is not substituted as activity.

Shock states are `NORMAL`, `EVENT_LIKE`, `DISCONTINUOUS`, and `UNCERTAIN`. Shock uses largest-return z-score, tail evidence, and path-share evidence.
