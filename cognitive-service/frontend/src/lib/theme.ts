// Engram theme — runtime side of the design-token system.
//
// The CSS-side palette lives in `src/styles/tokens.css`. This file mirrors
// just the bits needed for SVG/canvas/JS consumers (data viz mostly), and
// owns the source-of-truth `useTheme` hook that flips `data-theme` on <html>.

import { useSyncExternalStore } from 'react'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'engram-theme'
const ATTR        = 'data-theme'

// JS-side palette mirror — kept deliberately minimal. Only colors that need
// to render in <svg> / <canvas> live here; HTML/CSS components should consume
// the corresponding --engram-* CSS variables directly.
//
// Keep these in sync with src/styles/tokens.css. The viz palette is ordered
// to maximize perceptual distance within the Morandi space — picking the
// first N gives N visually distinguishable hues.
const PALETTE = {
  dark: {
    mauve:    '#B8A0A4',
    sage:     '#A3B89F',
    clay:     '#D0A892',
    slate:    '#9AA8B5',
    rust:     '#C0816A',
    mustard:  '#CCB67A',
    plum:     '#B098A8',
    textMuted:'#968F86',
    textQuiet:'#75716B',
    border:   '#3A3D42',
  },
  light: {
    mauve:    '#9E8B8E',
    sage:     '#8FA28E',
    clay:     '#B89481',
    slate:    '#7B8794',
    rust:     '#A36F5C',
    mustard:  '#B5A064',
    plum:     '#8E7585',
    textMuted:'#786F65',
    textQuiet:'#9C948A',
    border:   '#D9D2C7',
  },
} as const

export type VizPalette = {
  mauve:    string
  sage:     string
  clay:     string
  slate:    string
  rust:     string
  mustard:  string
  plum:     string
  textMuted:string
  textQuiet:string
  border:   string
}

// Ordered viz cycle for series with N keys (OCEAN, Schwartz, generic).
// Distinct enough at N=5; degrades gracefully past 7.
export function vizCycle(p: VizPalette): string[] {
  return [p.mauve, p.sage, p.clay, p.slate, p.rust, p.mustard, p.plum]
}

// Semantic mapping for OCEAN (5 dimensions). N is the most charged dimension —
// it gets rust (the most "tension-bearing" color in the palette).
export function oceanColors(p: VizPalette): Record<string, string> {
  return {
    O: p.slate,    // openness → cool sky
    C: p.sage,     // conscientiousness → grounded green
    E: p.clay,     // extraversion → warm clay
    A: p.mauve,    // agreeableness → soft mauve
    N: p.rust,     // neuroticism → tension
  }
}

// ── Domain (backbone) color assignment ────────────────────────────────────
//
// Color is a presentation concern and lives entirely on the frontend. The
// backend ships only the knowledge model (key/name/description); the UI
// computes a deterministic Morandi color from the sorted key index, so:
//
//   1. The same key always gets the same color across reloads.
//   2. Adding a new backbone alphabetically before an existing one shifts
//      downstream colors by one slot — accepted trade for distinctness in
//      the common case (≤ 7 backbones each get their own hue).
//   3. Light / dark themes have matched palettes — colors stay coherent
//      with the rest of the UI when the user toggles theme.

export function domainPalette(p: VizPalette): string[] {
  // Order tuned so the 6 shipped backbones (alphabetical: business, history,
  // philosophy, psychology, science, technology) line up with semantically
  // appropriate hues. The 7th slot is reserved for the first user-added
  // backbone; further additions cycle.
  return [
    p.mustard,  // 0 — business      (value / strength)
    p.rust,     // 1 — history       (earth / time)
    p.mauve,    // 2 — philosophy    (contemplation)
    p.plum,     // 3 — psychology    (emotional depth)
    p.sage,     // 4 — science       (rational / grounded)
    p.slate,    // 5 — technology    (cool / structured)
    p.clay,     // 6 — first user-added backbone
  ]
}

// Pure function: pick a color for `key` given a backbone list and the
// current theme palette. Use when you can't (or don't want to) call hooks.
// Unknown keys (e.g. orphaned domain references) fall back to text-quiet.
export function domainColor(
  key: string,
  backboneKeys: string[],
  palette: VizPalette,
): string {
  const sorted = [...backboneKeys].sort()
  const idx = sorted.indexOf(key)
  if (idx < 0) return palette.textQuiet
  const cycle = domainPalette(palette)
  return cycle[idx % cycle.length]
}

// React hook: returns a closure bound to the current theme palette. Use in
// components for the most ergonomic call site.
//   const colorOf = useDomainColor()
//   <span style={{ color: colorOf(domain, backbones) }} />
export function useDomainColor(): (key: string, backbones: { key: string }[]) => string {
  const { palette } = useTheme()
  return (key: string, backbones: { key: string }[]) =>
    domainColor(key, backbones.map(b => b.key), palette)
}

// ── Theme store (vanilla, framework-agnostic) ─────────────────────────────

let currentTheme: ThemeMode = readInitialTheme()
const listeners = new Set<() => void>()

function readInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'dark'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light'
  return 'dark'
}

function applyTheme(mode: ThemeMode) {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute(ATTR, mode)
}

export function setTheme(mode: ThemeMode) {
  if (mode === currentTheme) return
  currentTheme = mode
  try { window.localStorage.setItem(STORAGE_KEY, mode) } catch { /* ignore */ }
  applyTheme(mode)
  listeners.forEach(fn => fn())
}

export function toggleTheme() {
  setTheme(currentTheme === 'dark' ? 'light' : 'dark')
}

export function getTheme(): ThemeMode {
  return currentTheme
}

// Apply once at module load so the initial paint is correct (no flash).
if (typeof document !== 'undefined') applyTheme(currentTheme)

// ── React bindings ────────────────────────────────────────────────────────

function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  return () => { listeners.delete(cb) }
}

export function useTheme(): {
  theme: ThemeMode
  palette: VizPalette
  setTheme: (m: ThemeMode) => void
  toggle: () => void
} {
  const theme = useSyncExternalStore(subscribe, getTheme, getTheme)
  return {
    theme,
    palette: PALETTE[theme],
    setTheme,
    toggle: toggleTheme,
  }
}

