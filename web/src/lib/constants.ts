// ── Enum values ───────────────────────────────────────────────────────────────
//
// Domain values are NOT defined here — they come from the backend's
// /ui/api/backbones endpoint via `useBackbones()`. Use `getDomainLabel`
// to render the human label, and `useDomainColor()` from `lib/theme.ts`
// to resolve a theme-aware Morandi color.
//
// Node-type and relation-type are first-class graph enums shared across
// backbones, so they stay defined here.

import type { BackboneSchema } from '@/api'

// Domain color resolution moved to `lib/theme.ts` (theme-aware, frontend-owned).
// Import `useDomainColor` (hook) or `domainColor` (pure fn) from there.

export function getDomainLabel(key: string, backbones: BackboneSchema[], lang: 'zh' | 'en'): string {
  const bb = backbones.find(b => b.key === key)
  if (!bb) return key
  // Backend provides English `name`; for Chinese, fall back to a built-in
  // translation table for the default 6 backbones, otherwise show the key.
  if (lang === 'en') return bb.name || key
  return DOMAIN_LABELS_ZH_BUILTIN[key] ?? bb.name ?? key
}

// Built-in Chinese labels for the default 6 backbones shipped with the system.
// Custom user backbones display either their English `name` or the raw key in zh mode.
const DOMAIN_LABELS_ZH_BUILTIN: Record<string, string> = {
  business:   '商业',
  psychology: '心理学',
  history:    '历史',
  philosophy: '哲学',
  technology: '科技',
  science:    '科学',
}

export const TYPE_SHAPES: Record<string, string> = {
  person:  'ellipse',
  concept: 'round-rectangle',
  pattern: 'diamond',
  method:  'hexagon',
}

// Morandi-aligned. Cytoscape stylesheet consumes these as literal hex (CSS
// vars don't resolve in cytoscape), so values are picked to render readably
// on both light and dark canvases.
export const RELATION_COLORS: Record<string, string> = {
  similar:  '#9AA8B5',  // slate
  supports: '#D0A892',  // clay
  opposes:  '#C0816A',  // rust
  derives:  '#A3B89F',  // sage
  related:  '#75716B',  // muted neutral
}

const TYPE_LABELS_EN: Record<string, string> = {
  person:  'Person',
  concept: 'Concept',
  pattern: 'Pattern',
  method:  'Method',
}

const TYPE_LABELS_ZH: Record<string, string> = {
  person:  '人物',
  concept: '概念',
  pattern: '规律',
  method:  '方法',
}

const RELATION_LABELS_EN: Record<string, string> = {
  similar:  'similar',
  supports: 'supports',
  opposes:  'opposes',
  derives:  'derives',
  related:  'related',
}

const RELATION_LABELS_ZH: Record<string, string> = {
  similar:  '相似',
  supports: '支撑',
  opposes:  '对立',
  derives:  '推导',
  related:  '关联',
}

export function getTypeLabel(key: string, lang: 'zh' | 'en'): string {
  const map = lang === 'en' ? TYPE_LABELS_EN : TYPE_LABELS_ZH
  return map[key] ?? key
}

export function getRelationLabel(key: string, lang: 'zh' | 'en'): string {
  const map = lang === 'en' ? RELATION_LABELS_EN : RELATION_LABELS_ZH
  return map[key] ?? key
}

// ── Dimension display name maps ──────────────────────────────────────────
// Backbone schemas now carry their own labels; OCEAN / Schwartz name tables
// were removed as dead code. Re-add them only when a consumer actually
// needs static mappings (and prefer i18n keys when possible).

// Morandi 10-color cycle. ProfileTab uses theme-aware vizCycle() instead;
// these values are kept for any non-themed consumer.
export const SCHWARTZ_COLORS = [
  '#9E8B8E','#8FA28E','#B89481','#7B8794',
  '#A36F5C','#B5A064','#8E7585','#9AA8B5',
  '#A3B89F','#D0A892',
]
