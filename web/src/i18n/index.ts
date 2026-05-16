/**
 * Lightweight i18n. No external dependency.
 *
 * Usage:
 *   const { t, lang, setLang } = useI18n()
 *   t('common.cancel')
 *   t('admin.processed', { count: 5 })
 *
 * Wrap the app once with <LanguageProvider>. The active language is
 * persisted to localStorage as `engram_lang` and defaults to the
 * browser language (zh if it starts with 'zh', otherwise en).
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import zh, { type Dict } from './zh'
import en from './en'

export type Lang = 'zh' | 'en'

const DICTS: Record<Lang, Dict> = { zh, en }

const STORAGE_KEY = 'engram_lang'

// Module-level mirror of the active language. The LanguageProvider keeps it
// in sync; non-component utilities (like fmtTime) read it via getActiveLang
// so they stay in step with the current UI lang without taking it as a
// parameter at every call site.
let _activeLang: Lang = 'zh'
export function getActiveLang(): Lang {
  return _activeLang
}

function detectDefault(): Lang {
  if (typeof window === 'undefined') return 'zh'
  const saved = window.localStorage.getItem(STORAGE_KEY)
  if (saved === 'zh' || saved === 'en') return saved
  const nav = (window.navigator?.language || '').toLowerCase()
  return nav.startsWith('zh') ? 'zh' : 'en'
}

// ── Path helpers ────────────────────────────────────────────────────────────

// Build a union of all dotted paths "a.b.c" from a nested record. Recursive but
// bounded by Dict depth — avoids excessive instantiation.
type DottedPath<T, P extends string = ''> = {
  [K in keyof T & string]: T[K] extends Record<string, unknown>
    ? DottedPath<T[K], P extends '' ? K : `${P}.${K}`>
    : P extends '' ? K : `${P}.${K}`
}[keyof T & string]

export type TKey = DottedPath<Dict>

function lookup(dict: Dict, key: string): string | undefined {
  const parts = key.split('.')
  let cur: unknown = dict
  for (const p of parts) {
    if (cur && typeof cur === 'object' && p in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[p]
    } else {
      return undefined
    }
  }
  return typeof cur === 'string' ? cur : undefined
}

function interpolate(text: string, vars?: Record<string, string | number>): string {
  if (!vars) return text
  return text.replace(/\{(\w+)\}/g, (_, name) => {
    const v = vars[name]
    return v === undefined ? `{${name}}` : String(v)
  })
}

// ── Context ─────────────────────────────────────────────────────────────────

interface I18nContextValue {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: TKey, vars?: Record<string, string | number>) => string
}

const Ctx = createContext<I18nContextValue | null>(null)

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const initial = detectDefault()
    _activeLang = initial
    return initial
  })

  const setLang = useCallback((l: Lang) => {
    _activeLang = l
    setLangState(l)
    try { window.localStorage.setItem(STORAGE_KEY, l) } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    _activeLang = lang
    if (typeof document !== 'undefined') {
      document.documentElement.lang = lang
    }
  }, [lang])

  const t = useCallback(
    (key: TKey, vars?: Record<string, string | number>) => {
      const dict = DICTS[lang]
      const found = lookup(dict, key)
      if (found !== undefined) return interpolate(found, vars)
      // Fallback to the other language so nothing renders as a raw key
      const alt = lang === 'zh' ? en : zh
      const fallback = lookup(alt, key)
      if (fallback !== undefined) return interpolate(fallback, vars)
      return key
    },
    [lang],
  )

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return React.createElement(Ctx.Provider, { value }, children)
}

export function useI18n(): I18nContextValue {
  const v = useContext(Ctx)
  if (!v) throw new Error('useI18n must be used within <LanguageProvider>')
  return v
}
