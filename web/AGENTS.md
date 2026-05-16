# Frontend i18n contract

This file is the authoritative i18n rulebook for `web/`. Read it before adding, changing, or deleting any user-visible text.

## TL;DR

- Every user-visible string goes through `useI18n().t('namespace.key')`.
- Add a key in **both** `src/i18n/zh.ts` and `src/i18n/en.ts` (same path, same shape).
- Resolve domain / relation / node-type display via the helpers in `src/lib/constants.ts` — never hardcode them.

## Stack

- Source of truth dicts: `src/i18n/zh.ts` (primary, defines the `Dict` type) and `src/i18n/en.ts` (must satisfy `: Dict`).
- Hook: `useI18n()` from `src/i18n/index.ts` returns `{ lang, setLang, t }`.
- Type-checked: keys are validated by TypeScript via the `DottedPath<Dict>` union — typos at call sites fail `tsc`.

## Rules

### Adding a new user-visible string

1. Pick a namespace (`common` / `nav` / `graph` / `entries` / `query` / `profile` / `fieldHint` / `admin` / `import` / `language`). If none fits, propose a new one in the same PR; keep namespaces flat (no deeper than two levels).
2. Add the key to `zh.ts` first.
3. Mirror it in `en.ts` (TypeScript will fail otherwise).
4. Use it: `t('namespace.key')`. For interpolation: `t('namespace.key', { count: 5 })` and `'{count} items'` style placeholders inside the dict value.
5. If the component is a sub-component that doesn't already pull `useI18n`, add it locally — don't pass `t` as a prop.

### Changing an existing string

- If only the wording changes: edit both dicts.
- If the key is renamed: rename in both dicts AND every `t(...)` call site. `tsc` will catch you if you miss a call site.

### Deleting a string

- Remove from both dicts AND remove every `t(...)` reference. `tsc` will catch leftover references.

### Domain / relation / node-type display

- Domain key (`psychology`, `business`, …) → `getDomainColor(key, backbones)` and `getDomainLabel(key, backbones, lang)`. Pull `backbones` from `useBackbones()` and `lang` from `useI18n()`.
- Relation key (`opposes`, `supports`, …) → `getRelationLabel(key, lang)`.
- Node-type key (`person`, `concept`, …) → `getTypeLabel(key, lang)`.
- Never hardcode `DOMAIN_COLORS[key]` or string-literal Chinese / English domain names — they come from the backend `/ui/api/backbones` endpoint at runtime.

## What's allowed to be a literal

- JSX comments: `{/* ... */}` and `// ...` — these are dev-only.
- Decorative symbols: `'—' '·' '・' '◐' '▲' '▼' '✓' '✕' '✦'`.
- Brand / proper nouns: `'Engram'`, `'OCEAN'`, `'Schwartz'`, `'MCP'`, `'Markdown'`, `'JSON'`.
- Numerical / structural strings used as keys, IDs, classnames, CSS custom-property names.
- The `LangSwitcher` toggle label `'中'` / `'EN'` — that's intentionally bilingual UI.
- Labels in `*_KEYS` lookup tables (e.g. `STAGE_LABEL_KEYS`) where the *value* is a t-key string, not the displayed text.

## What is NOT allowed

- Any Chinese character inside a JSX text node, `placeholder`, `title`, `aria-label`, `alt`, `<button>` content, error `alert(...)`, `confirm({ message })`.
- Any English UI sentence written directly in JSX (e.g. `<button>Save</button>`). Use `t('common.save')` even when the dict value happens to be the same word.
- Hardcoded language toggling: never do `lang === 'zh' ? '关闭' : 'Close'` — put both in the dicts and let `t()` resolve.

## Backend strings

The backend (`api/`) is allowed to contain Chinese **only** in comments and docstrings. User-visible API responses (errors, messages, prompt section headers) must be English; LLM outputs match the user's language by instruction. See root `AGENTS.md` for canonical-English-enum rules.

## Verifying your work

Before committing a change touching components or i18n dicts:

```bash
cd web
npx tsc --noEmit       # catches missing keys, prop type mismatches
```

A green `tsc` is necessary but not sufficient — `tsc` cannot catch a string you wrote in JSX bypassing `t()`. Manually grep your diff:

```bash
# from web/
git diff --unified=0 src/components/ | grep -P '^\+' | grep -P '[\x{4e00}-\x{9fff}]'
```

Anything that returns from that grep should be a comment, a `t-key` lookup value, or one of the allowed literals above.

## Examples

❌ Don't:
```tsx
<button onClick={save}>保存</button>
<input placeholder="输入问题…" />
alert('写入失败: ' + err)
{lang === 'zh' ? '取消' : 'Cancel'}
```

✅ Do:
```tsx
<button onClick={save}>{t('common.save')}</button>
<input placeholder={t('query.placeholder_initial')} />
alert(t('entries.write_failed', { error: String(err) }))
{t('common.cancel')}
```
