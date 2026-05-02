import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import i18next from 'eslint-plugin-i18next'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // React 19 + eslint-plugin-react-hooks v7 ship React-Compiler-era rules
      // that are stricter than the runtime requires. We integrate imperative
      // libs (cytoscape) that legitimately need ref-during-render reads, so
      // these are kept as `warn` instead of `error`. The classic hooks rules
      // (rules-of-hooks, exhaustive-deps) stay at their default level.
      'react-hooks/refs': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
    },
  },
  // i18n: warn (not error) on hardcoded JSX text inside components.
  // Default mode 'jsx-text-only' already skips className/style/etc. attributes.
  // The full contract lives in cognitive-service/frontend/AGENTS.md.
  {
    files: ['src/components/**/*.{ts,tsx}'],
    plugins: { i18next },
    rules: {
      'i18next/no-literal-string': ['warn', {
        mode: 'jsx-text-only',
        words: {
          // Skips on top of the plugin defaults (numbers, all-caps,
          // punctuation, emoji, html entities). Keep this list short — when
          // in doubt, add a dict key instead of an exclusion.
          exclude: [
            // Brand / proper nouns
            '^Engram$', '^OCEAN$', '^Schwartz$', '^MCP$', '^Markdown$',
            '^JSON$', '^API$',
            // Bilingual UI markers (the LangSwitcher toggle)
            '^中$', '^EN$',
            // Decorative glyphs that occasionally render alone in a tag
            '^[—·・◐▲▼✓✕✦●■◆⬡◼◻▾▸→←]+$',
            // Technical field abbreviations used as graph/profile column
            // labels — universal jargon, not translated by design
            '^(conf|sim|strength|weight|delta|before|after)$',
            // Stage/turn IDs, e.g. R1, R2, Q1, Q2
            '^[A-Z]\\d+$',
          ],
        },
      }],
    },
  },
])
