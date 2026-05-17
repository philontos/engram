import { useState } from 'react'
import { useI18n } from '@/i18n'
import type { StageEvent, StageRowModel } from './types'
import { useStageEvents } from './useStageEvents'
import { StageRow } from './StageRow'
import { StageDetailDrawer } from './StageDetailDrawer'

/**
 * 顶层 pipeline 透明化组件。替代旧 ProcessPanel。
 *
 * - mode='live':  capture 刚发生，events 实时累积；entryId 为新 entry 的 id
 * - mode='replay': 用户点开历史 entry，重放该 entry 的处理过程
 */
export function PipelineInspector({
  entryId,
  events,
  done,
  mode = 'live',
}: {
  entryId: number
  events?: StageEvent[]
  done?: boolean
  mode?: 'live' | 'replay'
}) {
  const { t } = useI18n()
  const [openStage, setOpenStage] = useState<string | null>(null)
  const { rows, trace, traceLoading, traceError, loadTrace } = useStageEvents({
    entryId, mode, liveEvents: events,
  })

  const pipelineRow = rows.find(r => r.key === 'pipeline')
  const pipelineDone = done || (pipelineRow ? pipelineRow.status === 'done' || pipelineRow.status === 'error' : false)
  const llmCallsDone = rows.filter(r => r.status === 'done' && r.key !== 'pipeline').length
  const headerMs = pipelineRow?.durationMs ?? 0

  const grouped: Record<StageRowModel['group'], StageRowModel[]> = {
    slice: [], activation: [], backbone: [], pipeline: [],
  }
  for (const r of rows) {
    if (r.key === 'pipeline') continue
    grouped[r.group].push(r)
  }

  return (
    <div style={{
      marginTop: 8, padding: '10px 12px', fontSize: 11, lineHeight: 1.55,
      color: 'var(--text2)', background: 'var(--surface2)',
      border: '1px solid var(--border)', borderRadius: 6,
      transition: 'opacity 0.4s', opacity: pipelineDone ? 0.95 : 1,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 6, paddingBottom: 6, borderBottom: '1px solid var(--border)',
      }}>
        <span style={{ fontWeight: 600, color: 'var(--text)' }}>
          {pipelineDone
            ? (pipelineRow?.status === 'error'
                ? t('entries.process.header_failed')
                : t('entries.process.header_done', { ms: headerMs, calls: llmCallsDone }))
            : t('entries.process.header_running', { calls: llmCallsDone })}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>#{entryId}</span>
      </div>

      <Group label={t('entries.process.group_slice')} rows={grouped.slice}
             openStage={openStage} setOpenStage={setOpenStage}
             trace={trace} traceLoading={traceLoading} traceError={traceError} loadTrace={loadTrace} />
      <Group label={t('entries.process.group_activation')} rows={grouped.activation}
             openStage={openStage} setOpenStage={setOpenStage}
             trace={trace} traceLoading={traceLoading} traceError={traceError} loadTrace={loadTrace} />
      <Group label={t('entries.process.group_backbone')} rows={grouped.backbone}
             openStage={openStage} setOpenStage={setOpenStage}
             trace={trace} traceLoading={traceLoading} traceError={traceError} loadTrace={loadTrace} />
    </div>
  )
}

function Group(props: {
  label: string
  rows: StageRowModel[]
  openStage: string | null
  setOpenStage: (k: string | null) => void
  trace: ReturnType<typeof useStageEvents>['trace']
  traceLoading: boolean
  traceError: string | null
  loadTrace: () => Promise<void>
}) {
  const { label, rows, openStage, setOpenStage, trace, traceLoading, traceError, loadTrace } = props
  if (rows.length === 0) return null
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{
        fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase',
        letterSpacing: '0.5px', padding: '4px 10px',
      }}>{label}</div>
      {rows.map(r => (
        <div key={r.key}>
          <StageRow
            row={r}
            isOpen={openStage === r.key}
            onToggle={() => {
              const next = openStage === r.key ? null : r.key
              setOpenStage(next)
              if (next && !trace && !traceLoading) void loadTrace()
            }}
          />
          {openStage === r.key && (
            <StageDetailDrawer row={r} trace={trace} traceLoading={traceLoading} traceError={traceError} />
          )}
        </div>
      ))}
    </div>
  )
}
