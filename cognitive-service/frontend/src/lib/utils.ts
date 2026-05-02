/**
 * fmtTime: relative time formatter, language-aware.
 *
 * Pure function on purpose — call sites that already have an `lang` (from
 * useI18n) or a translator can pass it in. The default `lang='zh'` keeps
 * existing call sites working until they migrate.
 */
import zh from '@/i18n/zh'
import en from '@/i18n/en'
import type { Lang } from '@/i18n'

export function fmtTime(s: string, lang: Lang = 'zh'): string {
  const dict = lang === 'en' ? en : zh
  if (!s) return dict.common.empty_dash
  // SQLite returns UTC without timezone suffix; append Z so browsers don't misinterpret as local time
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  const normalized = hasTz ? s : s.replace(' ', 'T') + 'Z'
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return s.slice(0, 16)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return dict.common.just_now
  if (diff < 3600) return dict.common.minutes_ago.replace('{n}', String(Math.floor(diff / 60)))
  if (diff < 86400) return dict.common.hours_ago.replace('{n}', String(Math.floor(diff / 3600)))
  return `${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function cn(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(' ')
}
