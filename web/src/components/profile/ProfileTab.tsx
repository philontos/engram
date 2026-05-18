import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchProfile, fetchProfileEvolution } from '@/api'
import type { ProfileEvolution, EvolutionPoint } from '@/api'
import type { ProfileDimension, SubDimValue, SubSource, DimensionSchema } from '@/types'
import { useDimensionSchemas, getDimSchema } from '@/lib/useDimensionSchemas'
import { fmtTime } from '@/lib/utils'
import { useTheme, vizCycle, oceanColors } from '@/lib/theme'
import { useI18n } from '@/i18n'
import { ChevronDown, ChevronRight } from 'lucide-react'

type ProfileView = 'current' | 'evolution'

export function ProfileTab() {
  const { t } = useI18n()
  const [view, setView] = useState<ProfileView>('current')
  const { data: dims = [], isLoading } = useQuery({ queryKey: ['profile'], queryFn: fetchProfile })
  const { data: evolution } = useQuery({ queryKey: ['profile-evolution'], queryFn: fetchProfileEvolution })
  const schemas = useDimensionSchemas()

  if (isLoading) return <CenteredMessage>{t('profile.loading')}</CenteredMessage>
  if (!dims.length) return <CenteredMessage>{t('profile.empty')}</CenteredMessage>

  return (
    <div style={{
      height: '100%', overflowY: 'auto',
      background: 'var(--engram-bg-canvas)',
      color: 'var(--engram-text-primary)',
      padding: '32px 36px 48px',
      fontFamily: 'var(--engram-font-sans)',
    }}>
      {/* Page header — serif title sets the contemplative tone */}
      <header style={{ marginBottom: 24, maxWidth: 1200 }}>
        <h1 style={{
          fontFamily: 'var(--engram-font-serif)',
          fontSize: 26, fontWeight: 500, lineHeight: 1.2,
          color: 'var(--engram-text-primary)',
          letterSpacing: '0.005em',
        }}>
          {t('profile.title') || 'Profile'}
        </h1>
        <p style={{
          marginTop: 8, fontSize: 13,
          color: 'var(--engram-text-secondary)',
          maxWidth: 560, lineHeight: 1.7,
        }}>
          {t('profile.subtitle') || 'Dimensions accumulated from your reflections, not from your activity.'}
        </p>
      </header>

      {/* View switcher — segmented, low-saturation */}
      <ViewSwitcher view={view} onChange={setView} />

      {view === 'current' && (
        <div style={{
          // Multi-column "masonry-lite" layout: cards flow top-to-bottom into
          // each column, packing tightly regardless of individual card height.
          // Expanding a card only shifts cards beneath it in the same column —
          // other columns stay still. No JS required.
          columnWidth: 360,
          columnGap: 18,
          maxWidth: 1200,
        }}>
          {dims.map(dim => (
            <div key={dim.dimension} style={{
              breakInside: 'avoid',
              pageBreakInside: 'avoid',
              marginBottom: 18,
            }}>
              <DimensionCard dim={dim} schema={getDimSchema(schemas, dim.dimension)} />
            </div>
          ))}
        </div>
      )}

      {view === 'evolution' && evolution && <EvolutionPanel evolution={evolution} />}
      {view === 'evolution' && !evolution && (
        <div style={{ color: 'var(--engram-text-muted)', fontSize: 13 }}>{t('profile.loading')}</div>
      )}
    </div>
  )
}

// ── Layout primitives ─────────────────────────────────────────────────────

function CenteredMessage({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      height: '100%',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--engram-bg-canvas)',
      color: 'var(--engram-text-muted)',
      fontSize: 13,
      fontFamily: 'var(--engram-font-sans)',
    }}>
      {children}
    </div>
  )
}

function ViewSwitcher({ view, onChange }: { view: ProfileView; onChange: (v: ProfileView) => void }) {
  const { t } = useI18n()
  return (
    <div style={{
      display: 'inline-flex', gap: 0, marginBottom: 24,
      padding: 3,
      background: 'var(--engram-bg-surface)',
      border: '1px solid var(--engram-border-subtle)',
      borderRadius: 'var(--engram-radius-pill)',
    }}>
      {(['current', 'evolution'] as ProfileView[]).map(v => {
        const active = view === v
        return (
          <button key={v} onClick={() => onChange(v)}
            style={{
              padding: '6px 18px',
              borderRadius: 'var(--engram-radius-pill)',
              border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 500,
              fontFamily: 'inherit',
              background: active ? 'var(--engram-accent-primary)' : 'transparent',
              color: active ? 'var(--engram-bg-canvas)' : 'var(--engram-text-secondary)',
              transition: 'background var(--engram-transition), color var(--engram-transition)',
            }}>
            {v === 'current' ? t('profile.current') : t('profile.timeline')}
          </button>
        )
      })}
    </div>
  )
}

function ProfileCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--engram-bg-surface)',
      border: '1px solid var(--engram-border-subtle)',
      borderRadius: 'var(--engram-radius-lg)',
      padding: '22px 24px',
      // Width follows column; let it grow/shrink with viewport.
      transition: 'background var(--engram-transition)',
    }}>
      <div style={{ marginBottom: 18 }}>
        <div style={{
          fontFamily: 'var(--engram-font-serif)',
          fontSize: 15, fontWeight: 500,
          color: 'var(--engram-text-primary)',
          letterSpacing: '0.005em',
        }}>{title}</div>
        {subtitle && (
          <div style={{
            fontSize: 11, marginTop: 4,
            color: 'var(--engram-text-muted)',
          }}>{subtitle}</div>
        )}
      </div>
      {children}
    </div>
  )
}

// ── Dimension card ────────────────────────────────────────────────────────

function SourceList({ sources }: { sources: SubSource[] }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!sources.length) return null
  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={() => setOpen(v => !v)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--engram-text-muted)',
          fontSize: 10, padding: '2px 0',
          fontFamily: 'inherit',
        }}>
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        {t('profile.sources_n', { n: sources.length })}
      </button>
      {open && (
        <div style={{
          marginTop: 8, paddingLeft: 12,
          borderLeft: '2px solid var(--engram-border-subtle)',
          display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          {sources.map((s, i) => (
            <div key={i} style={{ fontSize: 11 }}>
              <div style={{
                display: 'flex', gap: 10, alignItems: 'center',
                color: 'var(--engram-text-muted)', marginBottom: 3,
              }}>
                <span style={{ color: 'var(--engram-accent-secondary)' }}>#{s.entry_id}</span>
                <span>{t('profile.score_label')}={s.score}</span>
                <span>{t('profile.confidence_label')}={s.confidence.toFixed(2)}</span>
                <span>{fmtTime(s.created_at)}</span>
              </div>
              {s.evidence && (
                <div style={{
                  color: 'var(--engram-text-secondary)',
                  fontSize: 12,
                  lineHeight: 1.75,
                }}>{s.evidence}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function DimensionCard({ dim, schema }: { dim: ProfileDimension; schema: DimensionSchema | undefined }) {
  const { t } = useI18n()
  const { palette } = useTheme()
  const c = dim.content
  const fmt = schema?.summary_format ?? 'free'
  const title = schema?.name ?? dim.dimension

  if (fmt === 'scores') {
    const entries: [string, string][] = schema?.sub_dimensions?.length
      ? schema.sub_dimensions.map(sd => [sd.key, sd.name])
      : Object.keys(c).map(k => [k, k])
    const sorted = schema?.sort_by_score
      ? [...entries].sort(([a], [b]) => ((c[b] as SubDimValue | null)?.score ?? 0) - ((c[a] as SubDimValue | null)?.score ?? 0))
      : entries

    // OCEAN keeps semantic mapping; everything else cycles the Morandi palette.
    const isOcean = dim.dimension === 'ocean'
    const oceanMap = oceanColors(palette)
    const cycle = vizCycle(palette)

    return (
      <ProfileCard title={title} subtitle={t('profile.based_on_n', { n: dim.sample_count })}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {sorted.map(([k, name], i) => {
            const v = (c[k] as SubDimValue | null) ?? { score: 50, confidence: 0 }
            const score = v.score ?? 50
            const conf  = v.confidence ?? 0
            const color = isOcean ? (oceanMap[k] || cycle[i % cycle.length]) : cycle[i % cycle.length]
            const sources = (dim.sub_sources[k] || []) as SubSource[]
            return (
              <div key={k}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 3 }}>
                  <span style={{
                    fontSize: 11, color: 'var(--engram-text-secondary)',
                    width: 90, flexShrink: 0,
                  }}>{name}</span>
                  <ScoreBar score={score} color={color} />
                  <span style={{
                    fontSize: 13, fontWeight: 500,
                    color: 'var(--engram-text-primary)',
                    width: 28, textAlign: 'right',
                    fontFamily: 'var(--engram-font-mono)',
                  }}>{Math.round(score)}</span>
                  <span style={{
                    fontSize: 10, color: 'var(--engram-text-quiet)',
                    width: 44, textAlign: 'right',
                    fontFamily: 'var(--engram-font-mono)',
                  }}>c={conf.toFixed(2)}</span>
                </div>
                <SourceList sources={sources} />
              </div>
            )
          })}
        </div>
      </ProfileCard>
    )
  }

  if (fmt === 'key_value') {
    const rows = Object.entries(c).filter(([, v]) => v && String(v) !== 'null')
    return (
      <ProfileCard title={title}>
        {rows.length === 0
          ? <div style={{ fontSize: 12, color: 'var(--engram-text-muted)' }}>{t('profile.no_data')}</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {rows.map(([k, v]) => {
                const val = typeof v === 'object' && v !== null && 'value' in v
                  ? String((v as Record<string, unknown>).value) : String(v ?? '')
                return (
                  <div key={k} style={{ display: 'flex', gap: 16, alignItems: 'baseline' }}>
                    <span style={{
                      fontSize: 11, color: 'var(--engram-text-muted)',
                      width: 90, flexShrink: 0,
                    }}>{k}</span>
                    <span style={{
                      fontSize: 13, color: 'var(--engram-text-primary)',
                      fontWeight: 500,
                    }}>{val}</span>
                  </div>
                )
              })}
            </div>
          )
        }
      </ProfileCard>
    )
  }

  return (
    <ProfileCard title={title} subtitle={t('profile.based_on_n', { n: dim.sample_count })}>
      <pre style={{
        fontSize: 11, color: 'var(--engram-text-muted)',
        fontFamily: 'var(--engram-font-mono)',
        margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      }}>
        {JSON.stringify(c, null, 2).substring(0, 300)}
      </pre>
    </ProfileCard>
  )
}

function ScoreBar({ score, color }: { score: number; color: string }) {
  return (
    <div style={{
      flex: 1, height: 6,
      background: 'var(--engram-border-subtle)',
      borderRadius: 'var(--engram-radius-pill)',
      overflow: 'hidden',
    }}>
      <div style={{
        height: '100%', width: `${score}%`, background: color,
        borderRadius: 'var(--engram-radius-pill)',
        transition: 'width 320ms cubic-bezier(0.2, 0, 0.2, 1)',
      }} />
    </div>
  )
}

// ── Evolution Panel ───────────────────────────────────────────────────────

// Catmull-Rom-style smooth curve through points. Tension ~0.28 gives visible
// curvature even with densely packed points. Returns an SVG path `d` string.
function smoothPath(pts: { x: number; y: number }[]): string {
  if (pts.length === 0) return ''
  if (pts.length === 1) return `M${pts[0].x},${pts[0].y}`
  if (pts.length === 2) return `M${pts[0].x},${pts[0].y} L${pts[1].x},${pts[1].y}`
  const t = 0.28
  let d = `M${pts[0].x},${pts[0].y}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1x = p1.x + (p2.x - p0.x) * t
    const c1y = p1.y + (p2.y - p0.y) * t
    const c2x = p2.x - (p3.x - p1.x) * t
    const c2y = p2.y - (p3.y - p1.y) * t
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2.x},${p2.y}`
  }
  return d
}

// Pick the most informative series when there are too many to plot legibly.
// Sort by latest score (descending) — final position is what users care about
// in an "evolution → current state" reading.
function pickTopSeries<T extends { points: EvolutionPoint[] }>(series: T[], n: number): T[] {
  if (series.length <= n) return series
  const scored = series.map(s => {
    const pts = s.points
    const last = pts.length ? pts[pts.length - 1].score : 0
    return { s, last }
  })
  scored.sort((a, b) => b.last - a.last)
  return scored.slice(0, n).map(x => x.s)
}

function EvolutionChart({ title, series, maxSeries }: {
  title: string
  series: { key: string; label: string; color: string; points: EvolutionPoint[] }[]
  maxSeries?: number
}) {
  const { t } = useI18n()
  const [showAll, setShowAll] = useState(false)
  const totalSeries = series.length
  const visibleSeries = !maxSeries || showAll ? series : pickTopSeries(series, maxSeries)
  const hiddenCount = totalSeries - visibleSeries.length

  const idToDate = new Map<number, string>()
  visibleSeries.forEach(s => s.points.forEach(p => { if (!idToDate.has(p.entry_id)) idToDate.set(p.entry_id, p.date) }))
  const allIds = Array.from(idToDate.keys()).sort((a, b) => a - b)

  if (allIds.length === 0) return (
    <div style={{ color: 'var(--engram-text-muted)', fontSize: 12 }}>{t('profile.no_data')}</div>
  )

  // Auto Y range: snap to data min/max with 10% padding, but enforce a minimum
  // visible window so flat-ish series don't look like dramatic noise.
  const allScores = visibleSeries.flatMap(s => s.points.map(p => p.score))
  const dataMin = Math.min(...allScores)
  const dataMax = Math.max(...allScores)
  const MIN_WINDOW = 20
  const center = (dataMin + dataMax) / 2
  let yMin = Math.max(0, dataMin - 5)
  let yMax = Math.min(100, dataMax + 5)
  if (yMax - yMin < MIN_WINDOW) {
    yMin = Math.max(0, center - MIN_WINDOW / 2)
    yMax = Math.min(100, center + MIN_WINDOW / 2)
  }
  // Pick 3-4 round-ish gridline values inside [yMin, yMax]
  const span = yMax - yMin
  const step = span > 60 ? 25 : span > 30 ? 15 : 10
  const firstTick = Math.ceil(yMin / step) * step
  const ticks: number[] = []
  for (let v = firstTick; v <= yMax; v += step) ticks.push(v)

  const W = 620, H = 200, PL = 36, PR = 14, PT = 14, PB = 30
  const cw = W - PL - PR
  const ch = H - PT - PB
  const xOf = (i: number) => PL + (allIds.length === 1 ? cw / 2 : (i / (allIds.length - 1)) * cw)
  const yOf = (score: number) => PT + ch - ((score - yMin) / (yMax - yMin)) * ch

  const MAX_LABELS = 6
  const labelStride = Math.max(1, Math.ceil(allIds.length / MAX_LABELS))
  const labelIndexes = new Set<number>()
  for (let i = 0; i < allIds.length; i += labelStride) labelIndexes.add(i)
  labelIndexes.add(allIds.length - 1)
  const shortDate = (iso: string) => (iso || '').slice(5, 10) || '—'

  // Hide per-point markers when the timeline is dense — line alone reads cleaner.
  const showMarkers = allIds.length <= 20

  return (
    <div style={{
      background: 'var(--engram-bg-surface)',
      border: '1px solid var(--engram-border-subtle)',
      borderRadius: 'var(--engram-radius-lg)',
      padding: '20px 22px',
      minWidth: 0,
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        marginBottom: 14, gap: 12,
      }}>
        <div style={{
          fontFamily: 'var(--engram-font-serif)',
          fontSize: 14, fontWeight: 500,
          color: 'var(--engram-text-primary)',
        }}>{title}</div>
        {hiddenCount > 0 && !showAll && (
          <button onClick={() => setShowAll(true)} style={{
            fontSize: 10, color: 'var(--engram-text-muted)',
            background: 'transparent', border: '1px solid var(--engram-border-subtle)',
            borderRadius: 6, padding: '2px 8px', cursor: 'pointer',
          }}>+{hiddenCount} more</button>
        )}
        {showAll && totalSeries > (maxSeries || 0) && (
          <button onClick={() => setShowAll(false)} style={{
            fontSize: 10, color: 'var(--engram-text-muted)',
            background: 'transparent', border: '1px solid var(--engram-border-subtle)',
            borderRadius: 6, padding: '2px 8px', cursor: 'pointer',
          }}>collapse</button>
        )}
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {ticks.map(v => (
          <g key={v}>
            <line x1={PL} y1={yOf(v)} x2={W - PR} y2={yOf(v)}
              stroke="var(--engram-border-subtle)"
              strokeWidth={0.7}
              strokeDasharray={'2 4'} />
            <text x={PL - 6} y={yOf(v) + 4} fontSize={11}
              fill="var(--engram-text-muted)" textAnchor="end">{v}</text>
          </g>
        ))}
        {allIds.map((id, i) => {
          const showLabel = labelIndexes.has(i)
          if (!showLabel) return null
          return (
            <g key={id}>
              <line x1={xOf(i)} y1={H - PB + 2} x2={xOf(i)} y2={H - PB + 5}
                stroke="var(--engram-border-subtle)" strokeWidth={0.6} />
              <text x={xOf(i)} y={H - 4} fontSize={9}
                fill="var(--engram-text-quiet)" textAnchor="middle">
                {shortDate(idToDate.get(id) || '')}
              </text>
            </g>
          )
        })}
        {visibleSeries.map(s => {
          const indexed = allIds
            .map((id, i) => ({ i, pt: s.points.find(p => p.entry_id === id) }))
            .filter(x => x.pt)
          if (indexed.length === 0) return null
          const xy = indexed.map(({ i, pt }) => ({ x: xOf(i), y: yOf(pt!.score) }))
          const d = smoothPath(xy)
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={1.6}
                strokeLinejoin="round" strokeLinecap="round" opacity={0.9} />
              {showMarkers && indexed.map(({ i, pt }) => (
                <circle key={`${s.key}-${i}`} cx={xOf(i)} cy={yOf(pt!.score)} r={2.5}
                  fill={s.color} opacity={0.55 + pt!.confidence * 0.45}>
                  <title>{`${s.label}: ${Math.round(pt!.score)} (c=${pt!.confidence.toFixed(2)})  ·  ${pt!.date}  ·  #${pt!.entry_id}`}</title>
                </circle>
              ))}
              {!showMarkers && indexed.map(({ i, pt }) => (
                <circle key={`${s.key}-${i}-hit`} cx={xOf(i)} cy={yOf(pt!.score)} r={6}
                  fill="transparent">
                  <title>{`${s.label}: ${Math.round(pt!.score)} (c=${pt!.confidence.toFixed(2)})  ·  ${pt!.date}  ·  #${pt!.entry_id}`}</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', marginTop: 12 }}>
        {visibleSeries.map(s => (
          <div key={s.key} style={{
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, color: 'var(--engram-text-muted)',
          }}>
            <span style={{
              width: 12, height: 2, borderRadius: 2, background: s.color,
            }} />
            {s.label}
          </div>
        ))}
      </div>
    </div>
  )
}

function EvolutionPanel({ evolution }: { evolution: ProfileEvolution }) {
  const { t } = useI18n()
  const { palette } = useTheme()
  const schemas = useDimensionSchemas()

  const dimEntries = Object.entries(evolution).filter(([, sub]) => Object.keys(sub).length > 0)
  if (dimEntries.length === 0) return (
    <div style={{ color: 'var(--engram-text-muted)', fontSize: 13 }}>{t('profile.no_evolution')}</div>
  )

  const cycle = vizCycle(palette)
  const oceanMap = oceanColors(palette)

  return (
    <div style={{
      display: 'grid',
      // Larger min-width so 4 dimensions naturally lay out 2x2 on a typical
      // dashboard (rather than 3+1). At smaller widths it falls back to 1 col.
      gridTemplateColumns: 'repeat(auto-fit, minmax(540px, 1fr))',
      gap: 18,
      alignItems: 'stretch',
      maxWidth: 1200,
    }}>
      {dimEntries.map(([dimKey, subMap]) => {
        const schema = getDimSchema(schemas, dimKey)
        const title = schema?.name || dimKey
        const subEntries = Object.entries(subMap)
        // Stride coprime with cycle length (7) when the dim has many series
        // — picks colors farther apart in the palette so adjacent lines don't
        // visually blend into a warm blob (Schwartz failure mode).
        const stride = subEntries.length > 6 ? 3 : 1
        const series = subEntries.map(([subKey, pts], i) => {
          const color = dimKey === 'ocean'
            ? (oceanMap[subKey] || cycle[i % cycle.length])
            : cycle[(i * stride) % cycle.length]
          return { key: subKey, label: subKey, color, points: pts }
        })
        // High-cardinality dims (Schwartz has 10) read as noise when all
        // shown at once. Cap to top-5 by latest score; user can expand.
        const maxSeries = series.length > 6 ? 5 : undefined
        return <EvolutionChart key={dimKey} title={title} series={series} maxSeries={maxSeries} />
      })}
    </div>
  )
}
