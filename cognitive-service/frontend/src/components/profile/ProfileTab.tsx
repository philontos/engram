import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchProfile, fetchProfileEvolution } from '@/api'
import type { ProfileEvolution, EvolutionPoint } from '@/api'
import type { ProfileDimension, SubDimValue, SubSource, DimensionSchema } from '@/types'
import { SCHWARTZ_COLORS } from '@/lib/constants'
import { useDimensionSchemas, getDimSchema } from '@/lib/useDimensionSchemas'
import { fmtTime } from '@/lib/utils'
import { useI18n } from '@/i18n'
import { ChevronDown, ChevronRight } from 'lucide-react'

type ProfileView = 'current' | 'evolution'

export function ProfileTab() {
  const { t } = useI18n()
  const [view, setView] = useState<ProfileView>('current')
  const { data: dims = [], isLoading } = useQuery({ queryKey: ['profile'], queryFn: fetchProfile })
  const { data: evolution } = useQuery({ queryKey: ['profile-evolution'], queryFn: fetchProfileEvolution })
  const schemas = useDimensionSchemas()

  if (isLoading) return (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text3)', fontSize: 13 }}>{t('profile.loading')}</div>
  )

  if (!dims.length) return (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text3)', fontSize: 13 }}>
      {t('profile.empty')}
    </div>
  )

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '28px 32px' }}>
      {/* Tab switcher */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 24 }}>
        {(['current', 'evolution'] as ProfileView[]).map(v => (
          <button key={v} onClick={() => setView(v)}
            style={{
              padding: '5px 14px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500,
              background: view === v ? 'var(--accent)' : 'var(--surface2)',
              color: view === v ? '#fff' : 'var(--text3)',
            }}>
            {v === 'current' ? t('profile.current') : t('profile.timeline')}
          </button>
        ))}
      </div>

      {view === 'current' && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, alignContent: 'flex-start', maxWidth: 1200 }}>
          {dims.map(dim => (
            <DimensionCard key={dim.dimension} dim={dim} schema={getDimSchema(schemas, dim.dimension)} />
          ))}
        </div>
      )}

      {view === 'evolution' && evolution && (
        <EvolutionPanel evolution={evolution} />
      )}
      {view === 'evolution' && !evolution && (
        <div style={{ color: 'var(--text3)', fontSize: 13 }}>{t('profile.loading')}</div>
      )}
    </div>
  )
}

function ProfileCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 14, padding: '20px 22px', minWidth: 340,
    }}>
      <div style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 3 }}>{subtitle}</div>}
      </div>
      {children}
    </div>
  )
}

function SourceList({ sources }: { sources: SubSource[] }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!sources.length) return null
  return (
    <div style={{ marginTop: 6 }}>
      <button onClick={() => setOpen(v => !v)}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 3, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', fontSize: 10, padding: '2px 0' }}>
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        {t('profile.sources_n', { n: sources.length })}
      </button>
      {open && (
        <div style={{ marginTop: 6, paddingLeft: 10, borderLeft: '2px solid var(--border2)', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sources.map((s, i) => (
            <div key={i} style={{ fontSize: 11 }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', color: 'var(--text3)', marginBottom: 2 }}>
                <span style={{ color: 'var(--accent2)' }}>#{s.entry_id}</span>
                <span>{t('profile.score_label')}={s.score}</span>
                <span>{t('profile.confidence_label')}={s.confidence.toFixed(2)}</span>
                <span>{fmtTime(s.created_at)}</span>
              </div>
              {s.evidence && <div style={{ color: 'var(--text3)', lineHeight: 1.5 }}>{s.evidence}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function DimensionCard({ dim, schema }: { dim: ProfileDimension; schema: DimensionSchema | undefined }) {
  const { t } = useI18n()
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
    return (
      <ProfileCard title={title} subtitle={t('profile.based_on_n', { n: dim.sample_count })}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {sorted.map(([k, name], i) => {
            const v = (c[k] as SubDimValue | null) ?? { score: 50, confidence: 0 }
            const score = v.score ?? 50
            const conf  = v.confidence ?? 0
            const color = SCHWARTZ_COLORS[i % SCHWARTZ_COLORS.length]
            const sources = (dim.sub_sources[k] || []) as SubSource[]
            return (
              <div key={k}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 2 }}>
                  <span style={{ fontSize: 11, color: 'var(--text2)', width: 80, flexShrink: 0 }}>{name}</span>
                  <div className="bar-track" style={{ height: 7 }}>
                    <div className="bar-fill" style={{ width: `${score}%`, background: color }} />
                  </div>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', width: 28, textAlign: 'right' }}>{Math.round(score)}</span>
                  <span style={{ fontSize: 10, color: 'var(--text3)', width: 40, textAlign: 'right' }}>c={conf.toFixed(2)}</span>
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
          ? <div style={{ fontSize: 12, color: 'var(--text3)' }}>{t('profile.no_data')}</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {rows.map(([k, v]) => {
                const val = typeof v === 'object' && v !== null && 'value' in v
                  ? String((v as Record<string, unknown>).value) : String(v ?? '')
                return (
                  <div key={k} style={{ display: 'flex', gap: 16, alignItems: 'baseline' }}>
                    <span style={{ fontSize: 11, color: 'var(--text3)', width: 80, flexShrink: 0 }}>{k}</span>
                    <span style={{ fontSize: 13, color: 'var(--text)', fontWeight: 500 }}>{val}</span>
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
      <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'monospace' }}>
        {JSON.stringify(c, null, 2).substring(0, 300)}
      </div>
    </ProfileCard>
  )
}

// ── Evolution Panel ────────────────────────────────────────────────────────────

const OCEAN_COLORS: Record<string, string> = {
  O: '#6366f1', C: '#10b981', E: '#f59e0b', A: '#ec4899', N: '#ef4444',
}

function EvolutionChart({ title, series }: {
  title: string
  series: { key: string; label: string; color: string; points: EvolutionPoint[] }[]
}) {
  const { t } = useI18n()
  const allIds = Array.from(
    new Set(series.flatMap(s => s.points.map(p => p.entry_id)))
  ).sort((a, b) => a - b)

  if (allIds.length === 0) return (
    <div style={{ color: 'var(--text3)', fontSize: 12 }}>{t('profile.no_data')}</div>
  )

  const W = 620, H = 220, PL = 32, PR = 12, PT = 12, PB = 32
  const cw = W - PL - PR
  const ch = H - PT - PB
  const xOf = (i: number) => PL + (allIds.length === 1 ? cw / 2 : (i / (allIds.length - 1)) * cw)
  const yOf = (score: number) => PT + ch - (score / 100) * ch

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '18px 20px', flex: '1 1 340px', minWidth: 0 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 12 }}>{title}</div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {[0, 25, 50, 75, 100].map(v => (
          <g key={v}>
            <line x1={PL} y1={yOf(v)} x2={W - PR} y2={yOf(v)}
              stroke="var(--border)" strokeWidth={v === 50 ? 1.5 : 1} strokeDasharray={v === 50 ? '4 3' : '2 3'} />
            <text x={PL - 4} y={yOf(v) + 4} fontSize={8} fill="var(--text3)" textAnchor="end">{v}</text>
          </g>
        ))}
        {allIds.map((id, i) => (
          <text key={id} x={xOf(i)} y={H - 2} fontSize={8} fill="var(--text3)" textAnchor="middle">#{id}</text>
        ))}
        {series.map(s => {
          const indexed = allIds
            .map((id, i) => ({ i, pt: s.points.find(p => p.entry_id === id) }))
            .filter(x => x.pt)
          if (indexed.length === 0) return null
          const d = indexed.map(({ i, pt }, j) => `${j === 0 ? 'M' : 'L'}${xOf(i)},${yOf(pt!.score)}`).join(' ')
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={1.8} strokeLinejoin="round" opacity={0.85} />
              {indexed.map(({ i, pt }) => (
                <circle key={`${s.key}-${i}`} cx={xOf(i)} cy={yOf(pt!.score)} r={3}
                  fill={s.color} opacity={0.6 + pt!.confidence * 0.4}>
                  <title>{s.label}: {Math.round(pt!.score)} (c={pt!.confidence.toFixed(2)})</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', marginTop: 10 }}>
        {series.map(s => (
          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--text3)' }}>
            <div style={{ width: 10, height: 3, borderRadius: 2, background: s.color }} />
            {s.label}
          </div>
        ))}
      </div>
    </div>
  )
}

function EvolutionPanel({ evolution }: { evolution: ProfileEvolution }) {
  const { t } = useI18n()
  const oceanSeries = Object.entries(evolution.ocean).map(([k, pts]) => ({
    key: k, label: k,
    color: OCEAN_COLORS[k] || '#888', points: pts,
  }))

  const schwartzSeries = Object.entries(evolution.schwartz).map(([k, pts], i) => ({
    key: k, label: k,
    color: SCHWARTZ_COLORS[i % SCHWARTZ_COLORS.length], points: pts,
  }))

  if (oceanSeries.length === 0 && schwartzSeries.length === 0) return (
    <div style={{ color: 'var(--text3)', fontSize: 13 }}>{t('profile.no_evolution')}</div>
  )

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, alignContent: 'flex-start' }}>
      {oceanSeries.length > 0 && <EvolutionChart title={t('profile.chart_ocean')} series={oceanSeries} />}
      {schwartzSeries.length > 0 && <EvolutionChart title={t('profile.chart_schwartz')} series={schwartzSeries} />}
    </div>
  )
}
