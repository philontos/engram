# MBTI Axis Scoring Guide

Each axis is a polar continuum. When there IS a signal, score 0–100 anchored to the two poles. When there is NO signal, return `null` for that axis (do not output `score=50, confidence=0.05`).

## E_I — Extraversion ↔ Introversion (0=I, 100=E)
- **Toward I (low)**: prefers solitude to recharge, talks less in groups, processes inwardly before speaking, drained by extended social contact.
- **Toward E (high)**: seeks out people for energy, thinks aloud, initiates contact, comfortable being the centre of conversations.

## S_N — Sensing ↔ Intuition (0=S, 100=N)
- **Toward S (low)**: focuses on concrete facts, present details, observed evidence, step-by-step procedure; trusts what is verifiable.
- **Toward N (high)**: focuses on patterns, abstractions, future possibilities, "what could be"; jumps across analogies and frameworks.

## T_F — Thinking ↔ Feeling (0=T, 100=F)
- **Toward T (low)**: decides by logic, principles, consistency, impersonal trade-offs; willing to deliver hard verdicts.
- **Toward F (high)**: decides by impact on people, values, harmony, personal meaning; weighs how the choice will land emotionally.

## J_P — Judging ↔ Perceiving (0=J, 100=P)
- **Toward J (low)**: prefers closure, plans, decisions, scheduled structure; uncomfortable with open loops.
- **Toward P (high)**: prefers keeping options open, adapting on the fly, exploring alternatives; resists locking in early.

# Score ranges (when there IS a signal)

| Score   | Meaning                                                |
|---------|--------------------------------------------------------|
| 0–20    | Strong expression of the LEFT pole                     |
| 20–40   | Mild lean to the LEFT pole                             |
| 40–60   | Genuinely balanced (only score here when entry shows mixed/balanced behaviour, not for "I'm not sure") |
| 60–80   | Mild lean to the RIGHT pole                            |
| 80–100  | Strong expression of the RIGHT pole                    |

# Confidence calibration

| Confidence | When to use                                                   |
|------------|---------------------------------------------------------------|
| 0.85–1.0   | Direct behavioural description or explicit self-report        |
| 0.6–0.85   | Indirect signal, reasonable inference                         |
| 0.4–0.6    | Weak hints only                                               |
| 0.2–0.4    | Tentative — consider whether `null` is more honest            |
| < 0.2      | Prefer `null` over a low-confidence score                     |

**`null` means "no signal in this entry" — the canonical way to abstain.** It's normal for 2–3 of the 4 MBTI axes to be `null` in a single entry.
