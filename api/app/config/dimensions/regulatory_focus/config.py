DIMENSION = {
    "key":             "regulatory_focus",
    "name":            "Regulatory Focus (Higgins)",
    "enabled":         True,
    "prompt_template": "extract.spt",
    "summary_format":  "scores",
    "summary_label":   "RegFocus",
    "sort_by_score":   True,
    "sub_dimensions": [
        {"key": "promotion",  "name": "Promotion Focus"},
        {"key": "prevention", "name": "Prevention Focus"},
    ],
    "score_range": [0, 100],
}
