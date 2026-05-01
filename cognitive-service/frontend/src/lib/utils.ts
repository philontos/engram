export function fmtTime(s: string): string {
  if (!s) return '—'
  // SQLite returns UTC without timezone suffix; append Z so browsers don't misinterpret as local time
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  const normalized = hasTz ? s : s.replace(' ', 'T') + 'Z'
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return s.slice(0, 16)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function cn(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(' ')
}
