DIMENSION = {
    "key":             "ocean",
    "name":            "Big Five Personality (OCEAN)",
    "enabled":         True,
    "prompt_template": "extract.spt",
    "summary_format":  "scores",       # render as key=score(conf=X) pairs
    "summary_label":   "OCEAN",
    "sort_by_score":   False,          # keep canonical O/C/E/A/N order
    "sub_dimensions": [
        {"key": "O", "name": "Openness"},
        {"key": "C", "name": "Conscientiousness"},
        {"key": "E", "name": "Extraversion"},
        {"key": "A", "name": "Agreeableness"},
        {"key": "N", "name": "Neuroticism"},
    ],
    "score_range": [0, 100],
}
