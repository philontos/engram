DIMENSION = {
    "key":             "schwartz",
    "name":            "Schwartz Basic Values",
    "enabled":         True,
    "prompt_template": "extract.spt",
    "summary_format":  "scores",       # render as key=score(conf=X) pairs
    "summary_label":   "Values",
    "sort_by_score":   True,           # sort descending by score
    "sub_dimensions": [
        {"key": "achievement",    "name": "Achievement"},
        {"key": "power",          "name": "Power"},
        {"key": "hedonism",       "name": "Hedonism"},
        {"key": "stimulation",    "name": "Stimulation"},
        {"key": "self_direction", "name": "Self-Direction"},
        {"key": "universalism",   "name": "Universalism"},
        {"key": "benevolence",    "name": "Benevolence"},
        {"key": "tradition",      "name": "Tradition"},
        {"key": "conformity",     "name": "Conformity"},
        {"key": "security",       "name": "Security"},
    ],
    "score_range": [0, 100],
}
