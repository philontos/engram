/**
 * Stage id → i18n key 映射。跟 slice_pipeline.py / backbone_pipeline.py
 * 的 stage 命名严格对应。
 *
 * Domain-specific stage（node_extract:psychology 等）走 prefix 匹配，
 * domain 名通过 getDomainLabel(domain, backbones, lang) 拼。
 */

import type { StageRowModel } from './types'

export const STAGE_LABEL_KEYS: Record<string, string> = {
  'pipeline':              'entries.process.stages.pipeline',
  'slice':                 'entries.process.stages.slice',
  'slice:situation':       'entries.process.stages.slice_situation',
  'slice:facts':           'entries.process.stages.slice_facts',
  'slice:mbti':            'entries.process.stages.slice_mbti',
  'slice:ocean':           'entries.process.stages.slice_ocean',
  'slice:regulatory_focus':'entries.process.stages.slice_reg_focus',
  'slice:schwartz':        'entries.process.stages.slice_schwartz',
  'activation':            'entries.process.stages.activation',
  'rough_retrieval':       'entries.process.stages.rough_retrieval',
  'node_resolution':       'entries.process.stages.node_resolution',
  'precise_retrieval':     'entries.process.stages.precise_retrieval',
  'algo_edges':            'entries.process.stages.algo_edges',
  'edge_extract':          'entries.process.stages.edge_extract',
  'association':           'entries.process.stages.association',
  'opposition_propagation':'entries.process.stages.opposition_propagation',
  'backbone':              'entries.process.stages.backbone',
}

/** node_extract:psychology / node_external:psychology — domain 部分分离 */
export function parseDomainStage(stage: string): { kind: 'internal' | 'external'; domain: string } | null {
  if (stage.startsWith('node_extract:')) return { kind: 'internal', domain: stage.slice('node_extract:'.length) }
  if (stage.startsWith('node_external:')) return { kind: 'external', domain: stage.slice('node_external:'.length) }
  return null
}

/** stage 归属的折叠组 */
export function stageGroup(stage: string): StageRowModel['group'] {
  if (stage === 'pipeline') return 'pipeline'
  if (stage.startsWith('slice') || stage === 'slice') return 'slice'
  if (stage === 'activation') return 'activation'
  return 'backbone'
}
