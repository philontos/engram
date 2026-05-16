BACKBONE = {
    # --- identity ---
    "key":         "my_domain",             # unique, English, used as DB domain field
    "name":        "My Domain",             # optional, human-readable label for UI; defaults to key
    "enabled":     True,                    # optional, set False to skip this backbone in the pipeline
    "description": "Brief description of this knowledge domain and what kinds of nodes it covers.",
    # Note: color is NOT a backbone concern — it's owned entirely by the
    # frontend (Morandi palette, theme-aware, deterministic by sorted key).
    # If you want to customize the palette, edit `web/src/lib/theme.ts`.

    # --- activation hints (injected into the shared activation prompt) ---
    # tell the LLM when this domain is worth activating for a given entry
    "focus_hints": [
        "Activate when the entry touches X, Y, or Z",
        "Prioritise nodes that explain the user's current state in this domain",
    ],
}
