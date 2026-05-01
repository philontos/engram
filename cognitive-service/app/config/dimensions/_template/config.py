DIMENSION = {
    # --- identity ---
    "key":             "my_dimension",          # unique, snake_case, English
    "name":            "My Dimension Name",     # human-readable
    "enabled":         True,

    # --- pipeline behaviour ---
    "merge":           True,    # False = only stored in slice_features, never merged into profile_dimensions
    "prompt_template": "extract.spt",

    # --- summary rendering (used by get_profile_summary / get_slice_summary) ---
    # "scores"    — each key has {score, confidence}; rendered as key=score(conf=X)
    # "key_value" — flat k/v or {value, evidence} shape; rendered as key=value pairs
    # "skip"      — excluded from all LLM context summaries (use for merge=False dims)
    # "free"      — fallback: json.dumps the full content
    "summary_format":  "scores",
    "summary_label":   "MyDim",

    # only relevant when summary_format="scores":
    "sort_by_score":   True,    # True = descending by score; False = dict key order

    # optional: if your dimension has well-known sub-keys, list them here for documentation
    # "sub_dimensions": [
    #     {"key": "sub_a", "name": "Sub A"},
    # ],
    # "score_range": [0, 100],
}
