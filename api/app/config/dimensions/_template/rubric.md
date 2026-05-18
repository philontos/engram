# Scoring rubric for [DIMENSION NAME]

## Sub-dimensions

**sub_key_a**: Describe what this measures. What behaviours/signals indicate high vs low scores.

**sub_key_b**: ...

## Score range reference

| Score | Meaning |
|-------|---------|
| 0–30  | Very low / strong opposite signal |
| 30–50 | Below average |
| 50–70 | Near average |
| 70–85 | Clearly elevated, concrete signal present |
| 85+   | Extreme — requires very strong evidence |

## Confidence calibration (when there IS a signal)

| Confidence | When to use |
|------------|-------------|
| 0.85–1.0 | Direct, explicit self-report or unambiguous behavioural description |
| 0.6–0.85 | Clear behavioural signal, reasonable inference |
| 0.4–0.6  | Indirect signal, real but weak |
| 0.2–0.4  | Tentative — consider whether `null` is more honest |
| < 0.2    | Prefer `null` over a low-confidence score |

**`null` means "no signal in this entry" — the canonical way to abstain.** Do not output `score=50, confidence=0.05` as a placeholder; the new schema expects `null` for that case.
