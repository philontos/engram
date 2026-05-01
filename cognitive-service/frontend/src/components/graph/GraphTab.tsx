import { useRef, useEffect, useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import cytoscape from 'cytoscape'
import type { Core, NodeSingular, EdgeSingular } from 'cytoscape'
import { fetchGraph } from '@/api'
import { DOMAIN_COLORS, TYPE_SHAPES, RELATION_COLORS } from '@/lib/constants'
import { fmtTime } from '@/lib/utils'

const DOMAINS = ['商业', '心理学', '历史', '哲学', '科技', '科学']

type NodeDetail = {
  kind: 'node'
  label: string; node_type: string; domain: string; origin: string
  weight: number; activation_count: number; last_activated: string
  user_relevance: string; factual_summary: string
  neighbors: { relation: string; dir: string; label: string; color: string }[]
}
type EdgeDetail = {
  kind: 'edge'
  relation: string; weight: number; confidence: number
  source_entries: number[]; srcLabel: string; tgtLabel: string
}
type Detail = NodeDetail | EdgeDetail

export function GraphTab({ active }: { active?: boolean }) {
  const [domain, setDomain] = useState('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const cyRef = useRef<Core | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const graphSignatureRef = useRef<string>('')

  useEffect(() => {
    if (active && cyRef.current) {
      cyRef.current.resize()
      cyRef.current.fit(undefined, 40)
    }
  }, [active])

  const { data, isLoading } = useQuery({
    queryKey: ['graph', domain],
    queryFn: () => fetchGraph(domain),
    staleTime: 5 * 60 * 1000,
  })

  const buildStyle = useCallback(() => [
    {
      selector: 'node',
      style: {
        'background-color': (ele: NodeSingular) => DOMAIN_COLORS[ele.data('domain') as string] || '#6366f1',
        'background-opacity': 0.9,
        label: 'data(label)',
        color: '#fff',
        'font-size': (ele: NodeSingular) => Math.max(9, Math.min(14, 9 + (ele.data('weight') as number) * 8)),
        'text-valign': 'center' as const,
        'text-halign': 'center' as const,
        'text-wrap': 'wrap' as const,
        'text-max-width': (ele: NodeSingular) => `${Math.max(60, Math.min(120, 60 + (ele.data('weight') as number) * 60))}px`,
        width: (ele: NodeSingular) => Math.max(40, Math.min(100, 40 + (ele.data('weight') as number) * 60)),
        height: (ele: NodeSingular) => Math.max(40, Math.min(100, 40 + (ele.data('weight') as number) * 60)),
        shape: (ele: NodeSingular) => TYPE_SHAPES[ele.data('node_type') as string] || 'ellipse',
        'border-color': (ele: NodeSingular) => DOMAIN_COLORS[ele.data('domain') as string] || '#6366f1',
        'border-width': (ele: NodeSingular) => (ele.data('weight') as number) * 2 + 1,
        'border-opacity': (ele: NodeSingular) => ele.data('origin') === 'external' ? 0.3 : 0.6,
        'background-blacken': (ele: NodeSingular) => ele.data('origin') === 'external' ? 0.3 : 0,
        'text-outline-color': '#0f1117',
        'text-outline-width': 1.5,
        'transition-property': 'background-opacity, border-width',
        'transition-duration': '0.15s',
      },
    },
    {
      selector: 'edge',
      style: {
        'line-color': (ele: EdgeSingular) => RELATION_COLORS[ele.data('relation') as string] || '#64748b',
        'target-arrow-color': (ele: EdgeSingular) => RELATION_COLORS[ele.data('relation') as string] || '#64748b',
        'target-arrow-shape': 'triangle' as const,
        'arrow-scale': 0.8,
        'line-style': (ele: EdgeSingular) => (ele.data('relation') === '相似' ? 'dashed' : 'solid') as 'dashed' | 'solid',
        'line-dash-pattern': [6, 3],
        width: (ele: EdgeSingular) => Math.max(1, (ele.data('weight') as number) * 3),
        opacity: 0.7,
        'curve-style': 'bezier' as const,
        label: 'data(relation)',
        'font-size': 9,
        color: '#64748b',
        'text-background-color': '#0f1117',
        'text-background-opacity': 0.8,
        'text-background-padding': '2px',
      },
    },
    { selector: 'node.highlighted', style: { 'background-opacity': 1, 'border-width': 4, 'border-color': '#fff', 'z-index': 10 } },
    { selector: 'node.faded', style: { 'background-opacity': 0.15, color: 'rgba(255,255,255,0.2)', 'text-outline-width': 0 } },
    { selector: 'edge.faded', style: { opacity: 0.08 } },
    { selector: 'node:selected', style: { 'border-color': '#fff', 'border-width': 4, 'background-opacity': 1 } },
  ], [])

  useEffect(() => {
    if (!containerRef.current || !data) return

    const signature = [
      ...data.nodes.map(n => n.data.id).sort(),
      '|',
      ...data.edges.map(e => e.data.id).sort(),
    ].join(',')

    if (cyRef.current && signature === graphSignatureRef.current) return
    graphSignatureRef.current = signature

    if (cyRef.current) {
      if (containerRef.current) containerRef.current.innerHTML = ''
      cyRef.current.destroy()
      cyRef.current = null
    }
    if (!data.nodes.length) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: [...data.nodes, ...data.edges],
      style: buildStyle() as never,
      layout: { name: 'cose', animate: true, animationDuration: 500, nodeRepulsion: 8000, idealEdgeLength: 120, gravity: 0.5, numIter: 1000 } as never,
      wheelSensitivity: 0.3,
    })

    const cy = cyRef.current

    cy.on('tap', 'node', (e) => {
      const node = e.target as NodeSingular
      cy.elements().removeClass('highlighted faded')
      node.addClass('highlighted')
      node.neighborhood('node').addClass('highlighted')
      node.neighborhood('edge').addClass('highlighted')
      cy.elements().not(node).not(node.neighborhood()).addClass('faded')

      const neighbors: NodeDetail['neighbors'] = []
      node.connectedEdges().forEach((edge) => {
        const other = edge.source().id() === node.id() ? edge.target() : edge.source()
        neighbors.push({
          relation: edge.data('relation') as string,
          dir: edge.source().id() === node.id() ? '→' : '←',
          label: other.data('label') as string,
          color: RELATION_COLORS[edge.data('relation') as string] || '#64748b',
        })
      })

      setDetail({
        kind: 'node',
        label: node.data('label') as string,
        node_type: node.data('node_type') as string,
        domain: node.data('domain') as string,
        origin: node.data('origin') as string,
        weight: node.data('weight') as number,
        activation_count: node.data('activation_count') as number,
        last_activated: node.data('last_activated') as string,
        user_relevance: node.data('user_relevance') as string,
        factual_summary: node.data('factual_summary') as string,
        neighbors,
      })
    })

    cy.on('tap', 'edge', (e) => {
      const edge = e.target as EdgeSingular
      setDetail({
        kind: 'edge',
        relation: edge.data('relation') as string,
        weight: edge.data('weight') as number,
        confidence: edge.data('confidence') as number,
        source_entries: (edge.data('source_entries') as number[]) || [],
        srcLabel: cy.getElementById(edge.data('source') as string).data('label') as string,
        tgtLabel: cy.getElementById(edge.data('target') as string).data('label') as string,
      })
    })

    cy.on('tap', (e) => {
      if (e.target === cy) {
        cy.elements().removeClass('highlighted faded')
        setDetail(null)
      }
    })

    cy.on('mouseover', 'node', (e) => { (e.target as NodeSingular).style('border-width', 3) })
    cy.on('mouseout', 'node', (e) => {
      const n = e.target as NodeSingular
      n.style('border-width', (n.data('weight') as number) * 2 + 1)
    })

    return () => {
      if (containerRef.current) containerRef.current.innerHTML = ''
      cyRef.current?.destroy()
      cyRef.current = null
    }
  }, [data, buildStyle])

  const relayout = () => {
    cyRef.current?.layout({ name: 'cose', animate: true, animationDuration: 800, nodeRepulsion: 8000, idealEdgeLength: 120, gravity: 0.5, numIter: 1000 } as never).run()
  }

  const closeDetail = () => {
    cyRef.current?.elements().removeClass('highlighted faded')
    setDetail(null)
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', flexShrink: 0, flexWrap: 'wrap', background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
        <DomainBtn label="全部" color="var(--accent)" active={domain === ''} onClick={() => setDomain('')} />
        {DOMAINS.map(d => (
          <DomainBtn key={d} label={d} color={DOMAIN_COLORS[d]} active={domain === d} onClick={() => setDomain(d)} />
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <ToolBtn onClick={relayout}>重新布局</ToolBtn>
          <ToolBtn onClick={() => cyRef.current?.fit()}>适应窗口</ToolBtn>
        </div>
      </div>

      {/* Graph + detail */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ position: 'relative', flex: 1, overflow: 'hidden' }}>
          {isLoading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text3)', fontSize: 13 }}>加载中…</div>
          )}
          {!isLoading && !data?.nodes.length && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: 'var(--text3)' }}>
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity={0.3}>
                <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" />
              </svg>
              <span style={{ fontSize: 13 }}>暂无图谱数据，请先写入记忆并处理</span>
            </div>
          )}
          <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
        </div>

        {detail && (
          <div className="fade-in" style={{ width: 288, flexShrink: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', background: 'var(--surface)', borderLeft: '1px solid var(--border)' }}>
            {/* Panel header */}
            <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                {detail.kind === 'node' && (() => {
                  const color = DOMAIN_COLORS[detail.domain] || '#6366f1'
                  return (
                    <>
                      <span className="badge" style={{ background: color + '22', color, marginBottom: 6, display: 'inline-flex' }}>
                        {detail.node_type} · {detail.domain}
                        {detail.origin === 'external' && <span style={{ opacity: 0.6, marginLeft: 4 }}>[外部]</span>}
                      </span>
                      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{detail.label}</div>
                    </>
                  )
                })()}
                {detail.kind === 'edge' && (() => {
                  const color = RELATION_COLORS[detail.relation] || '#64748b'
                  return (
                    <>
                      <span className="badge" style={{ background: color + '22', color, marginBottom: 6, display: 'inline-flex' }}>关系 · {detail.relation}</span>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{detail.srcLabel} → {detail.tgtLabel}</div>
                    </>
                  )
                })()}
              </div>
              <button onClick={closeDetail} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', fontSize: 16, lineHeight: 1, flexShrink: 0, padding: '0 2px' }}>✕</button>
            </div>
            {/* Panel body */}
            <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 14, fontSize: 12 }}>
              {detail.kind === 'node' && <NodeDetailBody d={detail} />}
              {detail.kind === 'edge' && <EdgeDetailBody d={detail} />}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '8px 16px', flexWrap: 'wrap', flexShrink: 0, background: 'var(--surface)', borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--text3)' }}>
        {DOMAINS.map(d => (
          <span key={d} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: DOMAIN_COLORS[d], flexShrink: 0 }} />{d}
          </span>
        ))}
        <span style={{ width: 1, height: 12, background: 'var(--border)', margin: '0 2px' }} />
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, borderTop: '2px dashed #94a3b8', display: 'inline-block' }} />相似</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, height: 2, background: '#818cf8', display: 'inline-block' }} />支撑</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, height: 2, background: '#f87171', display: 'inline-block' }} />对立</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, height: 2, background: '#34d399', display: 'inline-block' }} />演化</span>
        <span style={{ width: 1, height: 12, background: 'var(--border)', margin: '0 2px' }} />
        <span>● 人物 &nbsp;■ 概念 &nbsp;◆ 规律 &nbsp;⬡ 方法</span>
      </div>
    </div>
  )
}

function DomainBtn({ label, color, active, onClick }: { label: string; color: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      padding: '4px 13px', borderRadius: 99, border: `1px solid ${active ? color : 'var(--border2)'}`,
      background: active ? color : 'transparent', color: active ? '#fff' : 'var(--text2)',
      fontSize: 11, fontWeight: 500, cursor: 'pointer', transition: 'all 0.12s',
    }}>{label}</button>
  )
}

function ToolBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} style={{ padding: '4px 11px', borderRadius: 7, border: '1px solid var(--border2)', background: 'transparent', color: 'var(--text3)', fontSize: 11, cursor: 'pointer' }}>
      {children}
    </button>
  )
}

function Sec({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  )
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 11 }}>
      <span style={{ color: 'var(--text3)', width: 80, flexShrink: 0 }}>{label}</span>
      <span style={{ color: 'var(--text2)' }}>{value}</span>
    </div>
  )
}

function NodeDetailBody({ d }: { d: NodeDetail }) {
  return (
    <>
      <Sec title="权重">
        <div style={{ height: 6, borderRadius: 4, background: 'var(--surface3)', overflow: 'hidden', marginBottom: 8 }}>
          <div style={{ height: '100%', width: `${d.weight * 100}%`, background: 'var(--accent)', borderRadius: 4 }} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <KV label="personal_weight" value={d.weight.toFixed(4)} />
          <KV label="激活次数" value={String(d.activation_count)} />
          <KV label="最近激活" value={fmtTime(d.last_activated)} />
        </div>
      </Sec>
      {d.user_relevance && (
        <Sec title="与用户的关联">
          <p style={{ color: 'var(--text2)', lineHeight: 1.6, fontSize: 11 }}>{d.user_relevance}</p>
        </Sec>
      )}
      {d.factual_summary && (
        <Sec title="内容摘要">
          <p style={{ color: 'var(--text2)', lineHeight: 1.6, fontSize: 11 }}>{d.factual_summary}</p>
        </Sec>
      )}
      <Sec title="相邻节点">
        {d.neighbors.length === 0
          ? <p style={{ color: 'var(--text3)', fontSize: 11 }}>暂无关系</p>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {d.neighbors.map((n, i) => (
                <div key={i} style={{ padding: '7px 10px', borderRadius: 7, background: 'var(--surface2)', fontSize: 11 }}>
                  <span style={{ color: n.color, fontWeight: 600 }}>{n.relation}</span>
                  <span style={{ color: 'var(--text3)' }}> {n.dir} </span>
                  <span style={{ color: 'var(--text2)' }}>{n.label}</span>
                </div>
              ))}
            </div>
          )}
      </Sec>
    </>
  )
}

function EdgeDetailBody({ d }: { d: EdgeDetail }) {
  const color = RELATION_COLORS[d.relation] || '#64748b'
  return (
    <>
      <Sec title="关系属性">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <KV label="关系类型" value={d.relation} />
          <KV label="强度" value={d.weight.toFixed(3)} />
          <KV label="置信度" value={d.confidence.toFixed(3)} />
          <KV label="来源 Entry" value={d.source_entries.join(', ') || '—'} />
        </div>
      </Sec>
      <div style={{ height: 6, borderRadius: 4, background: 'var(--surface3)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${d.weight * 100}%`, background: color, borderRadius: 4 }} />
      </div>
    </>
  )
}
