import { useState, useMemo } from 'react'
import { useI18n } from '@/i18n'
import type { StageRowModel, TraceJson } from './types'

/**
 * 单 stage 展开详情：system_prompt / user_prompt / LLM response / parsed payload /
 * DB writes / heuristic flags。
 *
 * 数据来源：
 * - parsed payload + summary + error: 直接来自 row（已在内存中）
 * - prompt / response / DB writes: 从 trace 拉（lazy；调用方负责 traceLoading 状态）
 */
export function StageDetailDrawer({
  row,
  trace,
  traceLoading,
  traceError,
}: {
  row: StageRowModel
  trace: TraceJson | null
  traceLoading: boolean
  traceError: string | null
}) {
  const { t } = useI18n()

  const llmCall = useMemo(() => {
    if (!trace?.llm_calls) return null
    return trace.llm_calls.find(c => c.stage === row.key) ?? null
  }, [trace, row.key])

  return (
    <div style={{
      padding: '8px 12px 12px 22px',
      background: 'var(--surface)',
      borderLeft: '2px solid var(--engram-accent-primary, #8a7aa6)',
      fontSize: 11, lineHeight: 1.55,
    }}>
      {row.error && (
        <Section title={t('entries.process.detail.error_body')}>
          <pre style={preErrorStyle}>
            {(row.error.type ? `${row.error.type}: ` : '') + (row.error.message ?? '')}
          </pre>
        </Section>
      )}

      {row.reason && (
        <div style={{ color: 'var(--text3)', marginBottom: 6 }}>
          ({t('entries.process.status.skipped')}: {row.reason})
        </div>
      )}

      {row.payload && (
        <Section title={t('entries.process.detail.parsed_payload')}>
          <pre style={preCodeStyle}>{JSON.stringify(row.payload, null, 2)}</pre>
        </Section>
      )}

      {row.truncated && (
        <div style={{ color: 'var(--engram-accent-warning, #b96a52)', marginBottom: 6, fontSize: 10 }}>
          ⚠ {t('entries.process.detail.truncated_hint')}
        </div>
      )}

      {traceLoading && (
        <div style={{ color: 'var(--text3)', padding: '4px 0' }}>
          {t('entries.process.detail.loading')}
        </div>
      )}

      {traceError && (
        <div style={{ color: 'var(--engram-accent-warning, #b96a52)', padding: '4px 0' }}>
          {t('entries.process.detail.load_failed', { error: traceError })}
        </div>
      )}

      {llmCall && (
        <>
          <CollapsibleSection title={t('entries.process.detail.system_prompt')}>
            <pre style={preCodeStyle}>{llmCall.system_prompt ?? ''}</pre>
          </CollapsibleSection>
          {llmCall.user_prompt && (
            <Section title={t('entries.process.detail.user_prompt')}>
              <pre style={preCodeStyle}>{llmCall.user_prompt}</pre>
            </Section>
          )}
          <Section title={t('entries.process.detail.llm_response')}>
            <pre style={preCodeStyle}>{llmCall.response ?? ''}</pre>
          </Section>
        </>
      )}

      {!row.payload && !llmCall && !row.error && !traceLoading && (
        <div style={{ color: 'var(--text3)', padding: '4px 0' }}>
          {t('entries.process.detail.no_detail')}
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{
        fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase',
        letterSpacing: '0.5px', marginBottom: 3,
      }}>{title}</div>
      {children}
    </div>
  )
}

function CollapsibleSection({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ marginBottom: 8 }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase',
          letterSpacing: '0.5px', marginBottom: 3, cursor: 'pointer',
        }}
      >
        {open ? '▾' : '▸'} {title}
      </div>
      {open && children}
    </div>
  )
}

const preCodeStyle: React.CSSProperties = {
  background: 'var(--surface2)', padding: '6px 8px', borderRadius: 4,
  fontFamily: 'ui-monospace, monospace', fontSize: 10, lineHeight: 1.45,
  whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 260, overflow: 'auto',
  color: 'var(--text)',
}

const preErrorStyle: React.CSSProperties = {
  ...preCodeStyle,
  background: 'var(--engram-warn-surface, #3d2424)',
  color: 'var(--engram-accent-warning, #b96a52)',
}
