import { useRef, useEffect, useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import cytoscape from 'cytoscape'
import type { Core, NodeSingular, EdgeSingular } from 'cytoscape'
import { fetchGraphSeed, fetchGraphExpand } from '@/api'
import type { GraphNode, GraphEdge } from '@/types'
import { TYPE_SHAPES, RELATION_COLORS, getDomainColor, getDomainLabel, getRelationLabel } from '@/lib/constants'
import { fmtTime } from '@/lib/utils'
import { useI18n } from '@/i18n'
import { useBackbones } from '@/lib/useBackbones'

const SEED_LIMIT = 24

type NodeDetail = {
  kind: 'node'
  db_id: number
  label: string; node_type: string; domain: string; origin: string
  weight: number; activation_count: number; last_activated: string
  user_relevance: string; factual_summary: string
  unexpanded: number
  neighbors: { relation: string; dir: string; label: string; color: string }[]
}
type EdgeDetail = {
  kind: 'edge'
  relation: string; weight: number; confidence: number
  source_entries: number[]; srcLabel: string; tgtLabel: string
}
type Detail = NodeDetail | EdgeDetail

function nodeSize(weight: number) {
  // logarithmic scaling so a few high-weight nodes don't crush the rest
  const w = Math.max(0.01, weight)
  return 38 + Math.log10(1 + w * 9) * 56
}

export function GraphTab({ active }: { active?: boolean }) {
  const { lang, t } = useI18n()
  const { backbones } = useBackbones()
  const DOMAINS = backbones.map(b => b.key)
  const [domain, setDomain] = useState('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [focusId, setFocusId] = useState<number | null>(null)
  const cyRef = useRef<Core | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const expandedRef = useRef<Set<number>>(new Set())
  const focusIdRef = useRef<number | null>(null)
  const [expandingId, setExpandingId] = useState<number | null>(null)
  // Refs so handlers registered once don't capture stale callbacks
  const expandNodeRef = useRef<(id: number) => void>(() => {})
  const collapseNodeRef = useRef<(id: number) => void>(() => {})

  const { data: seed, isLoading } = useQuery({
    queryKey: ['graph-seed', domain],
    queryFn: () => fetchGraphSeed(domain, SEED_LIMIT),
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (active && cyRef.current) {
      cyRef.current.resize()
      cyRef.current.fit(undefined, 60)
    }
  }, [active])

  const buildStyle = useCallback(() => [
    {
      selector: 'node',
      style: {
        'background-color': (ele: NodeSingular) => getDomainColor(ele.data('domain') as string, backbones),
        'background-opacity': 0.92,
        'background-blacken': (ele: NodeSingular) => ele.data('origin') === 'external' ? 0.25 : -0.05,
        label: 'data(label)',
        color: '#fff',
        'font-size': (ele: NodeSingular) => Math.max(10, Math.min(15, 9 + Math.log10(1 + (ele.data('weight') as number) * 9) * 6)),
        'font-weight': 600 as never,
        'text-valign': 'center' as const,
        'text-halign': 'center' as const,
        'text-wrap': 'wrap' as const,
        'text-max-width': (ele: NodeSingular) => `${nodeSize(ele.data('weight') as number) - 16}px`,
        width:  (ele: NodeSingular) => nodeSize(ele.data('weight') as number),
        height: (ele: NodeSingular) => nodeSize(ele.data('weight') as number),
        shape: (ele: NodeSingular) => TYPE_SHAPES[ele.data('node_type') as string] || 'ellipse',
        'border-color': (ele: NodeSingular) => getDomainColor(ele.data('domain') as string, backbones),
        'border-width': 2,
        'border-opacity': 0.9,
        'text-outline-color': '#0a0d14',
        'text-outline-width': 2,
        'text-outline-opacity': 0.85,
        'overlay-padding': 6,
        'transition-property': 'background-opacity, border-width, border-color, opacity',
        'transition-duration': '0.18s',
      },
    },
    {
      selector: 'edge',
      style: {
        'line-color': (ele: EdgeSingular) => RELATION_COLORS[ele.data('relation') as string] || '#64748b',
        'target-arrow-color': (ele: EdgeSingular) => RELATION_COLORS[ele.data('relation') as string] || '#64748b',
        'target-arrow-shape': 'triangle' as const,
        'arrow-scale': 0.9,
        'line-style': (ele: EdgeSingular) => (ele.data('relation') === 'similar' ? 'dashed' : 'solid') as 'dashed' | 'solid',
        'line-dash-pattern': [6, 4],
        width: (ele: EdgeSingular) => Math.max(1.2, (ele.data('weight') as number) * 3.5),
        opacity: (ele: EdgeSingular) => 0.45 + Math.min(0.45, (ele.data('weight') as number) * 0.5),
        'curve-style': 'bezier' as const,
        'control-point-step-size': 60,
        label: 'data(relation)',
        'font-size': 9,
        color: '#94a3b8',
        'text-background-color': '#0a0d14',
        'text-background-opacity': 0.85,
        'text-background-padding': '3px',
        'text-rotation': 'autorotate' as const,
        'transition-property': 'opacity, width',
        'transition-duration': '0.2s',
      },
    },
    // ─── Layer order matters: later rules override earlier on overlapping properties ───

    // Layer 1 — Backgrounding (lowest priority)
    { selector: 'node.dim', style: { 'background-opacity': 0.18, color: 'rgba(255,255,255,0.25)', 'text-outline-opacity': 0.2, 'border-opacity': 0.2, 'z-index': 1 } },
    { selector: 'edge.dim',  style: { opacity: 0.06 } },

    // Layer 2 — Neighborhood emphasis
    { selector: 'node.hop2', style: { 'background-opacity': 0.55, 'border-opacity': 0.45 } },
    { selector: 'node.hop1', style: { 'background-opacity': 0.95, 'z-index': 20 } },
    { selector: 'edge.hop1', style: { opacity: 0.85, width: (ele: EdgeSingular) => Math.max(1.5, (ele.data('weight') as number) * 4) } },

    // Layer 3 — Persistent state markers
    // "Has hidden neighbors" — amber double border signals more to discover
    { selector: 'node.has-unexpanded', style: {
        'border-style': 'double' as never,
        'border-width': 5,
        'border-color': '#fbbf24',
        'border-opacity': 0.85,
    } },
    // "Already expanded by user" — teal outline ring signals visited
    { selector: 'node.expanded', style: {
        'outline-color': '#5eead4',
        'outline-width': 3,
        'outline-offset': 3,
        'outline-opacity': 0.65,
    } },

    // Layer 4 — Active focus (must dominate persistent markers)
    { selector: 'node.focus', style: {
        'border-width': 5,
        'border-color': '#ffffff',
        'border-opacity': 1,
        'border-style': 'solid' as never,
        'background-opacity': 1,
        'z-index': 30,
    } },

    // Layer 5 — Loading transient (briefly overrides focus to signal action)
    { selector: 'node.expanding', style: {
        'border-color': '#fbbf24',
        'border-width': 4,
        'border-style': 'dashed' as never,
    } },
  ], [])

  // ─── Highlight management ────────────────────────────────────────────────────
  const applyFocus = useCallback((nodeId: string | null) => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.elements().removeClass('focus hop1 hop2 dim')
      if (!nodeId) return
      const node = cy.getElementById(nodeId)
      if (!node || !node.length) return
      node.addClass('focus')
      const hop1Nodes = node.neighborhood('node')
      const hop1Edges = node.connectedEdges()
      hop1Nodes.addClass('hop1')
      hop1Edges.addClass('hop1')
      const hop2Nodes = hop1Nodes.neighborhood('node').difference(hop1Nodes).difference(node)
      hop2Nodes.addClass('hop2')
      cy.elements().not(node).not(hop1Nodes).not(hop1Edges).not(hop2Nodes).addClass('dim')
    })
  }, [])

  const buildNodeDetail = useCallback((node: NodeSingular): NodeDetail => {
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
    return {
      kind: 'node',
      db_id: node.data('db_id') as number,
      label: node.data('label') as string,
      node_type: node.data('node_type') as string,
      domain: node.data('domain') as string,
      origin: node.data('origin') as string,
      weight: node.data('weight') as number,
      activation_count: node.data('activation_count') as number,
      last_activated: node.data('last_activated') as string,
      user_relevance: node.data('user_relevance') as string,
      factual_summary: node.data('factual_summary') as string,
      unexpanded: (node.data('unexpanded_count') as number) || 0,
      neighbors,
    }
  }, [])

  // ─── Expand a node's neighbors ────────────────────────────────────────────────
  const expandNode = useCallback(async (dbId: number) => {
    const cy = cyRef.current
    if (!cy) return
    if (expandedRef.current.has(dbId)) return
    setExpandingId(dbId)
    const focusEle = cy.getElementById(`n${dbId}`)
    focusEle.addClass('expanding')
    try {
      const loadedIds = cy.nodes().map(n => n.data('db_id') as number)
      const data = await fetchGraphExpand(dbId, loadedIds)
      expandedRef.current.add(dbId)

      // Mark the focus as expanded — visual ring will appear
      focusEle.addClass('expanded')
      cy.batch(() => {
        // Place new nodes in the LARGEST EMPTY ANGULAR ARC around the focus,
        // so they don't overlap with the focus itself or existing neighbors.
        const center = focusEle.position()
        const focusRadius = nodeSize(focusEle.data('weight') as number) / 2
        const newNodes = (data.nodes as GraphNode[]).filter(n => !cy.getElementById(n.data.id).length)
        // Tag each new node with the expander that added it — used by collapse to
        // recursively unwind expansions (provenance tracking).
        newNodes.forEach(n => { (n.data as Record<string, unknown>).added_by = dbId })

        // Find angles of existing connected nodes (relative to focus)
        const occupied: number[] = []
        focusEle.connectedEdges().forEach(e => {
          const other = e.source().id() === focusEle.id() ? e.target() : e.source()
          const dx = other.position().x - center.x
          const dy = other.position().y - center.y
          if (dx * dx + dy * dy > 0.1) occupied.push(Math.atan2(dy, dx))
        })

        // Find the largest empty arc
        let arcStart = -Math.PI / 2
        let arcSize = 2 * Math.PI
        if (occupied.length > 0) {
          occupied.sort((a, b) => a - b)
          arcSize = 0
          for (let i = 0; i < occupied.length - 1; i++) {
            const gap = occupied[i + 1] - occupied[i]
            if (gap > arcSize) { arcSize = gap; arcStart = occupied[i] }
          }
          const wrap = (occupied[0] + 2 * Math.PI) - occupied[occupied.length - 1]
          if (wrap > arcSize) { arcSize = wrap; arcStart = occupied[occupied.length - 1] }
        }

        // Decide single-ring (arc-aware) vs multi-ring (full circle) layout.
        // Single ring fits within the available empty arc at base radius;
        // multi-ring fans out concentrically when too many neighbors to fit cleanly.
        const minSpacing = 130
        const baseRadius = focusRadius + 150
        const ringGap = 115

        // Sort new nodes by weight: stronger neighbors land in the inner ring(s)
        const sortedNew = [...newNodes].sort((a, b) => (b.data.weight || 0) - (a.data.weight || 0))

        // Compute target positions: array of {node, x, y}
        type Placed = { node: GraphNode; x: number; y: number }
        const placed: Placed[] = []

        const singleRingCap = Math.floor((arcSize * baseRadius) / minSpacing)
        const useMultiRing = sortedNew.length > Math.max(8, singleRingCap)

        if (!useMultiRing) {
          // Single ring inside the empty arc
          const minRadiusFromSpacing = arcSize > 0.1 ? ((sortedNew.length + 1) * minSpacing) / arcSize : 220
          const radius = Math.max(baseRadius, minRadiusFromSpacing)
          const sliceCount = sortedNew.length + 1
          sortedNew.forEach((n, i) => {
            const t = (i + 1) / sliceCount
            const angle = arcStart + arcSize * t
            placed.push({ node: n, x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle) })
          })
        } else {
          // Multi-ring full circle: fan nodes out so dense clusters stay readable
          let i = 0
          let ringLevel = 0
          while (i < sortedNew.length) {
            const r = baseRadius + ringLevel * ringGap
            const cap = Math.max(3, Math.floor((2 * Math.PI * r) / minSpacing))
            const remaining = sortedNew.length - i
            const inThisRing = Math.min(cap, remaining)
            // Stagger angles between rings for organic feel
            const angleOffset = ringLevel * 0.45
            for (let k = 0; k < inThisRing; k++) {
              const angle = (k / inThisRing) * 2 * Math.PI + angleOffset
              placed.push({
                node: sortedNew[i + k],
                x: center.x + r * Math.cos(angle),
                y: center.y + r * Math.sin(angle),
              })
            }
            i += inThisRing
            ringLevel++
          }
        }

        placed.forEach((p, i) => {
          // Start at focus center, transparent — animate to final position
          const ele = cy.add({ group: 'nodes', data: p.node.data, position: { x: center.x, y: center.y } } as never)
          ele.style('opacity', 0)
          // Stagger by index for graceful cascade; cap stagger to avoid long total time
          const delay = Math.min(15, 600 / Math.max(1, placed.length)) * i
          setTimeout(() => {
            ele.animate(
              { style: { opacity: 1 }, position: { x: p.x, y: p.y } } as never,
              { duration: 380, easing: 'ease-out' as never } as never,
            )
          }, delay)
        })
        ;(data.edges as GraphEdge[]).forEach(e => {
          if (!cy.getElementById(e.data.id).length) {
            const edge = cy.add({ group: 'edges', data: e.data } as never)
            edge.style('opacity', 0)
            setTimeout(() => {
              edge.animate({ style: { opacity: 1 } } as never, { duration: 320, easing: 'ease-out' as never } as never)
            }, 120)
          }
        })
        // Recompute unexpanded_count for ALL nodes — adding new neighbors can affect
        // multiple nodes' counts (a new node may also be a neighbor of others on screen).
        cy.nodes().forEach(node => {
          const total = (node.data('neighbor_count') as number) || 0
          const remaining = node.neighborhood('node').length
          const u = Math.max(0, total - remaining)
          node.data('unexpanded_count', u)
          if (u > 0) node.addClass('has-unexpanded')
          else node.removeClass('has-unexpanded')
        })
      })

      // Positions and animations are managed manually above — no layout needed
      // Refresh focus highlight to include newly-loaded neighbors
      if (focusIdRef.current === dbId) {
        applyFocus(focusEle.id())
        // Update side panel only if it's currently open for this node
        setDetail(prev => prev?.kind === 'node' && prev.db_id === dbId ? buildNodeDetail(focusEle as NodeSingular) : prev)
      }

      // After expansion settles, gently fit the focus + its neighborhood into view
      // (only when many new nodes — small expansions don't need a viewport shift).
      if (data.nodes.length > 8) {
        setTimeout(() => {
          const target = focusEle.closedNeighborhood()
          cy.animate({ fit: { eles: target, padding: 80 } } as never, { duration: 500, easing: 'ease-out' as never } as never)
        }, 450)
      }
    } finally {
      focusEle.removeClass('expanding')
      setExpandingId(null)
    }
  }, [applyFocus, buildNodeDetail])

  // ─── Collapse a node: BFS-remove its provenance descendants ──────────────────
  const collapseNode = useCallback(async (dbId: number) => {
    const cy = cyRef.current
    if (!cy) return
    const focusElId = `n${dbId}`
    const focus = cy.getElementById(focusElId)
    if (!focus.length) return

    // BFS: collect all nodes whose `added_by` traces back (transitively) to this focus.
    // A → expand → B (added_by=A); B → expand → C (added_by=B). Collapsing A removes both.
    const doomed = new Set<string>()
    const expanderQueue: number[] = [dbId]
    while (expanderQueue.length > 0) {
      const expander = expanderQueue.shift()!
      cy.nodes().forEach(n => {
        if (doomed.has(n.id())) return
        if (n.data('added_by') === expander) {
          doomed.add(n.id())
          expanderQueue.push(n.data('db_id') as number)
        }
      })
    }

    if (doomed.size === 0) return

    // ─── Animate: edges fade, nodes shrink toward focus ──────────────────────
    const focusPos = { x: focus.position().x, y: focus.position().y }
    const doomedNodeArr = Array.from(doomed).map(id => cy.getElementById(id))
    const doomedEdgeIds = new Set<string>()
    doomedNodeArr.forEach(n => {
      n.connectedEdges().forEach(e => { doomedEdgeIds.add(e.id()) })
    })

    // Fade edges first (snappier)
    doomedEdgeIds.forEach(id => {
      cy.getElementById(id).animate({ style: { opacity: 0 } } as never, { duration: 180, easing: 'ease-in' as never } as never)
    })

    // Nodes shrink + fade + drift toward focus
    await Promise.all(doomedNodeArr.map(n => new Promise<void>(resolve => {
      n.animate(
        { style: { opacity: 0 }, position: focusPos } as never,
        { duration: 280, easing: 'ease-in' as never, complete: () => resolve() } as never,
      )
    })))

    // The focus is no longer expanded — clear ring
    focus.removeClass('expanded')
    cy.batch(() => {
      // Remove doomed nodes (their edges are auto-removed)
      doomed.forEach(id => {
        cy.getElementById(id).remove()
        // Forget any expansion records for removed nodes
        const numericId = parseInt(id.slice(1), 10)
        expandedRef.current.delete(numericId)
      })
      // Re-mark focus as having unexpanded neighbors (since we removed some)
      const total = (focus.data('neighbor_count') as number) || 0
      const remaining = focus.neighborhood('node').length
      focus.data('unexpanded_count', Math.max(0, total - remaining))
      if (((focus.data('unexpanded_count') as number) || 0) > 0) focus.addClass('has-unexpanded')
      // Update remaining nodes' unexpanded markers (their neighbor counts are static)
      cy.nodes().forEach(n => {
        const u = (n.data('unexpanded_count') as number) || 0
        const localRemaining = n.neighborhood('node').length
        const localTotal = (n.data('neighbor_count') as number) || 0
        const newU = Math.max(u, localTotal - localRemaining)
        n.data('unexpanded_count', newU)
        if (newU > 0) n.addClass('has-unexpanded')
      })
      // Mark focus as no longer "expanded" so user can click it again to re-expand
      expandedRef.current.delete(dbId)
    })

    // Refresh side panel ONLY if it's already open for this node — don't auto-open it
    setDetail(prev => prev?.kind === 'node' && prev.db_id === dbId ? buildNodeDetail(focus as NodeSingular) : prev)
  }, [buildNodeDetail])

  // Keep refs in sync so the once-registered tap handlers always call the latest fn
  useEffect(() => { expandNodeRef.current = expandNode }, [expandNode])
  useEffect(() => { collapseNodeRef.current = collapseNode }, [collapseNode])
  useEffect(() => { focusIdRef.current = focusId }, [focusId])

  // ─── Initialize cytoscape with seed ──────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || !seed) return

    if (!cyRef.current) {
      cyRef.current = cytoscape({
        container: containerRef.current,
        elements: [...seed.nodes, ...seed.edges],
        style: buildStyle() as never,
        layout: {
          name: 'concentric',
          animate: true,
          animationDuration: 450,
          fit: true,
          padding: 60,
          startAngle: -Math.PI / 2,
          minNodeSpacing: 28,
          concentric: (n: NodeSingular) => n.data('weight') as number,
          levelWidth: () => 1.6,
        } as never,
        wheelSensitivity: 0.25,
        pixelRatio: 'auto' as never,
      })
      const cy = cyRef.current

      cy.on('tap', 'node', (e) => {
        const node = e.target as NodeSingular
        const dbId = node.data('db_id') as number
        const wasFocused = focusIdRef.current === dbId
        applyFocus(node.id())
        setFocusId(dbId)
        if (wasFocused && expandedRef.current.has(dbId)) {
          collapseNodeRef.current(dbId)
        } else if (!expandedRef.current.has(dbId)) {
          expandNodeRef.current(dbId)
        }
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
          applyFocus(null)
          setFocusId(null)
          setDetail(null)
        }
      })

      // Mark initial unexpanded nodes
      cy.nodes().forEach(node => {
        const u = (node.data('unexpanded_count') as number) || 0
        if (u > 0) node.addClass('has-unexpanded')
      })
    } else {
      // Domain switched: rebuild seed without destroying cy
      const cy = cyRef.current
      cy.batch(() => {
        cy.elements().remove()
        cy.add([...seed.nodes, ...seed.edges] as never)
        cy.nodes().forEach(node => {
          const u = (node.data('unexpanded_count') as number) || 0
          if (u > 0) node.addClass('has-unexpanded')
        })
      })
      expandedRef.current.clear()
      setFocusId(null)
      setDetail(null)
      cy.layout({
        name: 'concentric',
        animate: true,
        animationDuration: 450,
        fit: true,
        padding: 60,
        startAngle: -Math.PI / 2,
        minNodeSpacing: 28,
        concentric: (n: NodeSingular) => n.data('weight') as number,
        levelWidth: () => 1.6,
      } as never).run()
    }
    // Only re-run when seed reference changes (domain switch / refetch).
    // Callbacks are accessed via refs to avoid recreating the cytoscape instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed])

  useEffect(() => {
    return () => {
      cyRef.current?.destroy()
      cyRef.current = null
    }
  }, [])

  const closeDetail = () => {
    applyFocus(null)
    setFocusId(null)
    setDetail(null)
  }

  const recenter = () => {
    cyRef.current?.fit(undefined, 60)
  }

  const reset = () => {
    const cy = cyRef.current
    if (!cy || !seed) return
    cy.batch(() => {
      cy.elements().remove()
      cy.add([...seed.nodes, ...seed.edges] as never)
      cy.nodes().forEach(node => {
        const u = (node.data('unexpanded_count') as number) || 0
        if (u > 0) node.addClass('has-unexpanded')
      })
    })
    expandedRef.current.clear()
    setFocusId(null)
    setDetail(null)
    cy.layout({
      name: 'concentric',
      animate: true,
      animationDuration: 450,
      fit: true,
      padding: 60,
      startAngle: -Math.PI / 2,
      minNodeSpacing: 28,
      concentric: (n: NodeSingular) => n.data('weight') as number,
      levelWidth: () => 1.6,
    } as never).run()
  }

  const loadedCount = cyRef.current?.nodes().length ?? 0

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', flexShrink: 0, flexWrap: 'wrap', background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
        <DomainBtn label={t('graph.all')} color="var(--accent)" active={domain === ''} onClick={() => setDomain('')} />
        {DOMAINS.map(d => (
          <DomainBtn key={d} label={getDomainLabel(d, backbones, lang)} color={getDomainColor(d, backbones)} active={domain === d} onClick={() => setDomain(d)} />
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text3)', marginRight: 4 }}>{t('graph.nodes_hint', { count: loadedCount })}</span>
          <ToolBtn onClick={reset}>{t('graph.reset')}</ToolBtn>
          <ToolBtn onClick={recenter}>{t('graph.fit_window')}</ToolBtn>
        </div>
      </div>

      {/* Graph + detail */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{
          position: 'relative', flex: 1, overflow: 'hidden',
          background: 'radial-gradient(ellipse at center, #141926 0%, #0a0d14 75%)',
        }}>
          {/* Decorative grid overlay */}
          <div style={{
            position: 'absolute', inset: 0, pointerEvents: 'none',
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.04) 1px, transparent 1px)',
            backgroundSize: '32px 32px',
            maskImage: 'radial-gradient(ellipse at center, black 50%, transparent 90%)',
            WebkitMaskImage: 'radial-gradient(ellipse at center, black 50%, transparent 90%)',
          }} />
          {isLoading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text3)', fontSize: 13, zIndex: 5 }}>
              <span className="pulse">{t('common.loading')}</span>
            </div>
          )}
          {!isLoading && !seed?.nodes.length && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: 'var(--text3)', zIndex: 5 }}>
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity={0.3}>
                <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" />
              </svg>
              <span style={{ fontSize: 13 }}>{t('graph.empty')}</span>
            </div>
          )}
          {expandingId !== null && (
            <div style={{
              position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
              background: 'rgba(20,25,38,0.85)', border: '1px solid var(--border)',
              padding: '6px 14px', borderRadius: 99, fontSize: 11, color: 'var(--text2)',
              zIndex: 10, backdropFilter: 'blur(6px)',
            }}>
              <span style={{ color: '#fbbf24', marginRight: 6 }}>◐</span> {t('graph.expanding')}
            </div>
          )}
          {focusId !== null && expandingId === null && (() => {
            const node = cyRef.current?.getElementById(`n${focusId}`)
            if (!node?.length) return null
            const label = node.data('label') as string
            const dom = node.data('domain') as string
            const color = getDomainColor(dom, backbones)
            const isOpen = detail?.kind === 'node' && detail.db_id === focusId
            return (
              <div className="fade-in" style={{
                position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
                background: 'rgba(20,25,38,0.92)', border: '1px solid var(--border)',
                padding: '6px 6px 6px 14px', borderRadius: 99, fontSize: 12,
                zIndex: 10, backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', gap: 10,
                maxWidth: 'calc(100% - 32px)',
              }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
                <span style={{ color: 'var(--text)', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 240 }}>{label}</span>
                <button
                  onClick={() => {
                    if (isOpen) {
                      setDetail(null)
                    } else {
                      const n = cyRef.current?.getElementById(`n${focusId}`)
                      if (n?.length) setDetail(buildNodeDetail(n as NodeSingular))
                    }
                  }}
                  style={{
                    background: isOpen ? 'var(--surface2)' : 'var(--accent)',
                    color: isOpen ? 'var(--text2)' : '#fff',
                    border: 'none', borderRadius: 99, padding: '4px 12px',
                    fontSize: 11, fontWeight: 500, cursor: 'pointer',
                  }}>
                  {isOpen ? t('graph.close_detail') : t('graph.open_detail')}
                </button>
              </div>
            )
          })()}
          <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative', zIndex: 1 }} />
        </div>

        {detail && (
          <div className="fade-in" style={{ width: 320, flexShrink: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', background: 'var(--surface)', borderLeft: '1px solid var(--border)' }}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                {detail.kind === 'node' && (() => {
                  const color = getDomainColor(detail.domain, backbones)
                  return (
                    <>
                      <span className="badge" style={{ background: color + '22', color, marginBottom: 6, display: 'inline-flex' }}>
                        {detail.node_type} · {detail.domain}
                        {detail.origin === 'external' && <span style={{ opacity: 0.6, marginLeft: 4 }}>{t('graph.external_tag')}</span>}
                      </span>
                      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', lineHeight: 1.3 }}>{detail.label}</div>
                      {detail.unexpanded > 0 && (
                        <div style={{ fontSize: 11, color: '#fbbf24', marginTop: 4 }}>
                          {t('graph.unexpanded_hint', { n: detail.unexpanded })}
                        </div>
                      )}
                    </>
                  )
                })()}
                {detail.kind === 'edge' && (() => {
                  const color = RELATION_COLORS[detail.relation] || '#64748b'
                  return (
                    <>
                      <span className="badge" style={{ background: color + '22', color, marginBottom: 6, display: 'inline-flex' }}>{t('graph.relation_prefix')} · {getRelationLabel(detail.relation, lang)}</span>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{detail.srcLabel} → {detail.tgtLabel}</div>
                    </>
                  )
                })()}
              </div>
              <button onClick={closeDetail} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', fontSize: 16, lineHeight: 1, flexShrink: 0, padding: '0 2px' }}>✕</button>
            </div>
            <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 14, fontSize: 12 }}>
              {detail.kind === 'node' && (
                <NodeDetailBody
                  d={detail}
                  isExpanded={focusId !== null && expandedRef.current.has(focusId)}
                  onExpand={() => focusId !== null && expandNode(focusId)}
                  onCollapse={() => focusId !== null && collapseNode(focusId)}
                  expanding={expandingId !== null}
                />
              )}
              {detail.kind === 'edge' && <EdgeDetailBody d={detail} />}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '8px 16px', flexWrap: 'wrap', flexShrink: 0, background: 'var(--surface)', borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--text3)' }}>
        {DOMAINS.map(d => (
          <span key={d} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: getDomainColor(d, backbones), flexShrink: 0 }} />{getDomainLabel(d, backbones, lang)}
          </span>
        ))}
        <span style={{ width: 1, height: 12, background: 'var(--border)', margin: '0 2px' }} />
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, borderTop: '2px dashed #94a3b8', display: 'inline-block' }} />{getRelationLabel('similar', lang)}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, height: 2, background: '#818cf8', display: 'inline-block' }} />{getRelationLabel('supports', lang)}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, height: 2, background: '#f87171', display: 'inline-block' }} />{getRelationLabel('opposes', lang)}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 18, height: 2, background: '#34d399', display: 'inline-block' }} />{getRelationLabel('derives', lang)}</span>
        <span style={{ width: 1, height: 12, background: 'var(--border)', margin: '0 2px' }} />
        <span>{t('graph.legend_shapes')}</span>
        <span style={{ width: 1, height: 12, background: 'var(--border)', margin: '0 2px' }} />
        <span style={{ color: '#fbbf24' }}>{t('graph.legend_pending')}</span>
        <span style={{ color: '#5eead4' }}>{t('graph.legend_expanded')}</span>
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

function NodeDetailBody({ d, isExpanded, onExpand, onCollapse, expanding }: {
  d: NodeDetail; isExpanded: boolean; onExpand: () => void; onCollapse: () => void; expanding: boolean
}) {
  const { t } = useI18n()
  return (
    <>
      <Sec title={t('graph.weight')}>
        <div style={{ height: 6, borderRadius: 4, background: 'var(--surface3)', overflow: 'hidden', marginBottom: 8 }}>
          <div style={{ height: '100%', width: `${Math.min(100, d.weight * 100)}%`, background: 'var(--accent)', borderRadius: 4 }} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <KV label={t('graph.strength_short')} value={d.weight.toFixed(4)} />
          <KV label={t('graph.activation_count')} value={String(d.activation_count)} />
          <KV label={t('graph.last_activation')} value={fmtTime(d.last_activated)} />
        </div>
      </Sec>
      <div style={{ display: 'flex', gap: 6 }}>
        {d.unexpanded > 0 && (
          <button
            onClick={onExpand}
            disabled={expanding}
            style={{
              flex: 1, padding: '8px 12px', borderRadius: 8,
              border: '1px solid #fbbf24', background: 'rgba(251,191,36,0.12)',
              color: '#fbbf24', fontSize: 11, fontWeight: 500,
              cursor: expanding ? 'wait' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            }}>
            {expanding ? t('graph.expanding_label') : t('graph.expand_n', { n: d.unexpanded })}
          </button>
        )}
        {isExpanded && (
          <button
            onClick={onCollapse}
            style={{
              flex: 1, padding: '8px 12px', borderRadius: 8,
              border: '1px solid var(--border2)', background: 'var(--surface2)',
              color: 'var(--text2)', fontSize: 11, fontWeight: 500, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            }}>
            {t('graph.collapse_branch')}
          </button>
        )}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: -8 }}>
        {t('graph.click_to_collapse')}
      </div>
      {d.user_relevance && (
        <Sec title={t('graph.user_relevance')}>
          <p style={{ color: 'var(--text2)', lineHeight: 1.6, fontSize: 11 }}>{d.user_relevance}</p>
        </Sec>
      )}
      {d.factual_summary && (
        <Sec title={t('graph.summary')}>
          <p style={{ color: 'var(--text2)', lineHeight: 1.6, fontSize: 11 }}>{d.factual_summary}</p>
        </Sec>
      )}
      <Sec title={t('graph.neighbors_n', { n: d.neighbors.length })}>
        {d.neighbors.length === 0
          ? <p style={{ color: 'var(--text3)', fontSize: 11 }}>{t('graph.no_neighbors')}</p>
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
  const { t, lang } = useI18n()
  const color = RELATION_COLORS[d.relation] || '#64748b'
  return (
    <>
      <Sec title={t('graph.edge_props')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <KV label={t('graph.relation_type')} value={getRelationLabel(d.relation, lang)} />
          <KV label={t('graph.strength')} value={d.weight.toFixed(3)} />
          <KV label={t('graph.confidence')} value={d.confidence.toFixed(3)} />
          <KV label={t('graph.source_entry')} value={d.source_entries.join(', ') || '—'} />
        </div>
      </Sec>
      <div style={{ height: 6, borderRadius: 4, background: 'var(--surface3)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.min(100, d.weight * 100)}%`, background: color, borderRadius: 4 }} />
      </div>
    </>
  )
}
