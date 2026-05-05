# Schwartz Basic Values Scoring Guide

**Achievement**: Drive for personal success, demonstrating competence, and social recognition. Signals: focus on outcomes, competitive mindset, self-evaluation against standards.
**Power**: Desire for control over resources, status, and others. Signals: pursuit of influence, hierarchy-consciousness, valuing authority.
**Hedonism**: Seeking pleasure and sensory gratification. Signals: emphasis on comfort, entertainment, present-moment enjoyment.
**Stimulation**: Craving novelty, challenge, and excitement. Signals: welcoming change, boredom with routine, actively seeking new experiences.
**Self-Direction**: Freedom to think and act independently. Signals: insistence on autonomy, creativity, resistance to external constraint.
**Universalism**: Understanding and concern for all people and nature. Signals: focus on fairness and justice, environmental awareness, openness to diverse cultures.
**Benevolence**: Care and support for people in one's immediate circle. Signals: loyalty, altruism, dedication to family and close friends.
**Tradition**: Respect for and preservation of cultural customs and heritage. Signals: valuing historical continuity, following conventions, religious observance.
**Conformity**: Compliance with social norms to avoid harming others. Signals: rule-following, politeness, self-restraint.
**Security**: Need for stability, harmony, and safety. Signals: risk avoidance, desire for order, preference for certainty.

# Score ranges (when there IS a signal)

| Score | Meaning |
|-------|---------|
| 0–20  | Value rarely expressed, possibly reversed |
| 20–40 | Below average |
| 40–60 | Moderate |
| 60–80 | Clearly expressed, distinct behavioral signals present |
| 80+   | Core value — dominates behavior and decision-making |

# Confidence calibration

| Confidence | When to use |
|------------|-------------|
| 0.85–1.0 | Direct statement or strong behavioral signal |
| 0.6–0.85 | Indirect signal, reasonable inference |
| 0.4–0.6  | Weak signal |
| 0.2–0.4  | Tentative — consider whether `null` is more honest |
| < 0.2    | Prefer `null` over a low-confidence score |

**`null` means "no signal in this entry" — the canonical way to abstain.** Schwartz values are sparse — typical entries express 1–3 of the 10 values, so 7–9 should be `null`.
