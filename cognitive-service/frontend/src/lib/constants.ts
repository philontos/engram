// ── Enum values ───────────────────────────────────────────────────────────────
//
// Domain values are NOT defined here — they come from the backend's
// /ui/api/backbones endpoint via `useBackbones()`. Use `getDomainColor` /
// `getDomainLabel` to resolve a backbone key against the live catalog.
//
// Node-type and relation-type are first-class graph enums shared across
// backbones, so they stay defined here.

import type { BackboneSchema } from '@/api'

const FALLBACK_COLOR = '#64748b'

export function getDomainColor(key: string, backbones: BackboneSchema[]): string {
  return backbones.find(b => b.key === key)?.color ?? FALLBACK_COLOR
}

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

export const RELATION_COLORS: Record<string, string> = {
  similar:  '#94a3b8',
  supports: '#818cf8',
  opposes:  '#f87171',
  derives:  '#34d399',
  related:  '#64748b',
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

// ── Profile dimension display names ───────────────────────────────────────────

export const OCEAN_NAMES_ZH: Record<string, string> = {
  O: '开放性', C: '尽责性', E: '外向性', A: '宜人性', N: '神经质',
}

export const OCEAN_NAMES_EN: Record<string, string> = {
  O: 'Openness', C: 'Conscientiousness', E: 'Extraversion', A: 'Agreeableness', N: 'Neuroticism',
}

export const SCHWARTZ_NAMES_ZH: Record<string, string> = {
  achievement:    '成就',
  power:          '权力',
  hedonism:       '享乐',
  stimulation:    '刺激',
  self_direction: '自我导向',
  universalism:   '普世主义',
  benevolence:    '仁慈',
  tradition:      '传统',
  conformity:     '顺从',
  security:       '安全',
}

export const SCHWARTZ_NAMES_EN: Record<string, string> = {
  achievement:    'Achievement',
  power:          'Power',
  hedonism:       'Hedonism',
  stimulation:    'Stimulation',
  self_direction: 'Self-Direction',
  universalism:   'Universalism',
  benevolence:    'Benevolence',
  tradition:      'Tradition',
  conformity:     'Conformity',
  security:       'Security',
}

// Backwards-compatibility re-exports (some files still import these names).
// Components migrating to i18n should pick the right map via lang.
export const OCEAN_NAMES = OCEAN_NAMES_ZH
export const SCHWARTZ_NAMES = SCHWARTZ_NAMES_ZH

export const SCHWARTZ_COLORS = [
  '#6366f1','#8b5cf6','#a855f7','#ec4899',
  '#f43f5e','#f59e0b','#10b981','#3b82f6',
  '#06b6d4','#84cc16',
]
