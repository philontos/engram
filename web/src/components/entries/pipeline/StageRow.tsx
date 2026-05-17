import { useI18n } from '@/i18n'
import { useBackbones } from '@/lib/useBackbones'
import { getDomainLabel } from '@/lib/constants'
import type { StageRowModel } from './types'
import { STAGE_LABEL_KEYS, parseDomainStage } from './stageLabels'

/**
 * 单 stage 行：状态点 + 名称 + 耗时 + summary。整行点击触发外层 onExpand。
 */
export function StageRow({
  row,
  isOpen,
  onToggle,
}: {
  row: StageRowModel
  isOpen: boolean
  onToggle: () => void
}) {
  const { t, lang } = useI18n()
  const { backbones } = useBackbones()

  const label = resolveStageLabel(row.key, t, lang, backbones)

  return (
    <div
      onClick={onToggle}
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 10px',
        cursor: 'pointer',
        background: isOpen ? 'var(--surface2)' : 'transparent',
        borderLeft: isOpen ? '2px solid var(--engram-accent-primary, #8a7aa6)' : '2px solid transparent',
        fontSize: 11, lineHeight: 1.55,
      }}
    >
      <StatusDot status={row.status} />
      <span style={{ flex: 1, color: 'var(--text)' }}>{label}</span>
      {row.durationMs > 0 && (
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>
          {(row.durationMs / 1000).toFixed(1)}s
        </span>
      )}
      {row.summary && (
        <span style={{
          fontSize: 10, color: 'var(--text2)',
          maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {row.summary}
        </span>
      )}
      {row.truncated && (
        <span style={{
          fontSize: 9, color: 'var(--engram-accent-warning, #b96a52)', fontWeight: 600,
        }} title={t('entries.process.detail.truncated_hint')}>
          …
        </span>
      )}
    </div>
  )
}

function resolveStageLabel(
  stage: string,
  t: ReturnType<typeof useI18n>['t'],
  lang: ReturnType<typeof useI18n>['lang'],
  backbones: ReturnType<typeof useBackbones>['backbones'],
): string {
  const ds = parseDomainStage(stage)
  if (ds) {
    const domainLabel = getDomainLabel(ds.domain, backbones, lang)
    const tk = ds.kind === 'internal'
      ? 'entries.process.stages.node_extract_internal'
      : 'entries.process.stages.node_extract_external'
    return t(tk as any, { domain: domainLabel })
  }
  const key = STAGE_LABEL_KEYS[stage]
  if (!key) return stage
  return t(key as any)
}

function StatusDot({ status }: { status: StageRowModel['status'] }) {
  const color =
    status === 'done'    ? 'var(--engram-accent-success, #6b8e6b)' :
    status === 'error'   ? 'var(--engram-accent-warning, #b96a52)' :
    status === 'skipped' ? 'var(--text3)' :
    status === 'running' ? 'var(--engram-accent-primary, #8a7aa6)' :
                            'var(--border2)'
  const animated = status === 'running'
  return (
    <span style={{
      width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0,
      animation: animated ? 'pulse 1.2s ease-in-out infinite' : 'none',
    }} />
  )
}
