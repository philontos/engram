DIMENSION = {
    "key":             "mbti",
    "name":            "Myers-Briggs (MBTI)",
    "enabled":         True,
    "merge":           True,
    "prompt_template": "extract.spt",

    # Each axis stored as a single 0-100 score where 0 and 100 are the two poles
    # (see sub_dimensions for which letter is at which end). 50 = balanced /
    # no signal in this entry. profile_merge averages over time, so the long
    # term value reflects the user's typical lean.
    "summary_format":  "scores",
    "summary_label":   "MBTI",
    "sort_by_score":   False,        # keep canonical E/I, S/N, T/F, J/P axis order

    "sub_dimensions": [
        {"key": "E_I", "name": "Extraversion ↔ Introversion (0=I, 100=E)"},
        {"key": "S_N", "name": "Sensing       ↔ Intuition    (0=S, 100=N)"},
        {"key": "T_F", "name": "Thinking      ↔ Feeling      (0=T, 100=F)"},
        {"key": "J_P", "name": "Judging       ↔ Perceiving   (0=J, 100=P)"},
    ],
    "score_range": [0, 100],
}
