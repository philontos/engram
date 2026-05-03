import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchQueryLogs, fetchQueryLog, clearQueryLogs, deleteQueryLog } from '@/api'
import type { QueryLogDetail, QueryTurn, ToolCallTrace, ThemeRecall } from '@/types'
import { getDomainColor, getDomainLabel } from '@/lib/constants'
import { useBackbones } from '@/lib/useBackbones'
import { useI18n } from '@/i18n'
import { fmtTime } from '@/lib/utils'
import { Send, Square, Trash2, Clock, MessageSquarePlus } from 'lucide-react'
import { useConfirm } from '@/components/ui/ConfirmDialog'

type NodeDetail = { id: number; label: string; domain: string; origin: string; strength: number; sim?: number | null; description?: string }
type EdgeDetail = { from_label: string; relation_type: string; to_label: string; weight: number; from_id?: number; to_id?: number }
type ToolCallDetail = { nodes?: NodeDetail[]; edges?: EdgeDetail[]; [k: string]: unknown }
type AgentToolCall = {
  callId: string
  round: number
  tool: string
  args: Record<string, unknown>
  summary?: string
  detail?: ToolCallDetail
  latencyMs?: number
}
type AgentRound = {
  round: number
  thinking: string
  toolCalls: AgentToolCall[]
  finishReason?: string
  hadToolCalls?: boolean
}
type ConvTurn = {
  id: string
  question: string
  intent?: string
  intentMessage?: string
  rounds: AgentRound[]
  finalRoundIndex?: number
  done: boolean
  createdAt: number
}
type QueuedQuery = { question: string; sessionId: string | null }

// v2 — agent-mode shape; bump key so stale phase-based payloads do not hydrate.
const SESSION_KEY_TURNS   = 'query_turns_v2'
const SESSION_KEY_BASE    = 'query_base_log_v2'
const SESSION_KEY_SID     = 'query_session_id_v2'
const SESSION_KEY_LID     = 'query_log_id_v2'

function loadSession<T>(key: string): T | null {
  try { const v = sessionStorage.getItem(key); return v ? JSON.parse(v) as T : null } catch { return null }
}
function saveSession(key: string, value: unknown) {
  try { sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* ignore */ }
}
function clearSession() {
  try {
    sessionStorage.removeItem(SESSION_KEY_TURNS)
    sessionStorage.removeItem(SESSION_KEY_BASE)
    sessionStorage.removeItem(SESSION_KEY_SID)
    sessionStorage.removeItem(SESSION_KEY_LID)
  } catch { /* ignore */ }
}

// Tool label keys (resolved through i18n at render time).
const TOOL_LABEL_KEYS: Record<string, string> = {
  recall_raw:            'query.tool_recall_raw',
  recall_raw_by_node:    'query.tool_recall_raw_by_node',
  search_graph:          'query.tool_search_graph',
  expand_node:           'query.tool_expand_node',
  get_node_neighborhood: 'query.tool_get_neighborhood',
  get_opposites:         'query.tool_get_opposites',
  compare_nodes:         'query.tool_compare_nodes',
  list_blindspots:       'query.tool_list_blindspots',
  list_bridges:          'query.tool_list_bridges',
  find_evolution_paths:  'query.tool_find_paths',
  get_persona_lens:      'query.tool_persona_lens',
  recall_history_answer:      'query.tool_history_answer',
  recall_history_tools:       'query.tool_history_tools',
  recall_history_tool_detail: 'query.tool_history_tool_detail',
  web_search:            'query.tool_web_search',
}

const TOOL_COLORS: Record<string, string> = {
  recall_raw:            '#10b981',
  recall_raw_by_node:    '#10b981',
  search_graph:          '#6366f1',
  expand_node:           '#6366f1',
  get_node_neighborhood: '#6366f1',
  get_opposites:         '#f87171',
  compare_nodes:         '#f87171',
  list_blindspots:       '#f87171',
  list_bridges:          '#a78bfa',
  find_evolution_paths:  '#a78bfa',
  get_persona_lens:      '#f59e0b',
  recall_history_answer:      '#0ea5e9',
  recall_history_tools:       '#0ea5e9',
  recall_history_tool_detail: '#0ea5e9',
  web_search:            '#f59e0b',
}


export function QueryTab() {
  const qc = useQueryClient()
  const { backbones } = useBackbones()
  const { t } = useI18n()
  const [question, setQuestion] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [queueLength, setQueueLength] = useState(0)
  const [turns, setTurns]           = useState<ConvTurn[]>(() => (loadSession<ConvTurn[]>(SESSION_KEY_TURNS) ?? []).map((t, i) => ({ ...t, id: t.id ?? String(i), done: true })))
  const [baseLog, setBaseLog]       = useState<QueryLogDetail | null>(() => loadSession<QueryLogDetail>(SESSION_KEY_BASE))
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(() => loadSession<string>(SESSION_KEY_SID))
  const [currentLogId, setCurrentLogId] = useState<number | null>(() => loadSession<number>(SESSION_KEY_LID))
  const [error, setError]           = useState('')
  const [selectedLogId, setSelectedLogId] = useState<number | null>(null)

  // logs 加载后默认选中第一条
  const logsInitialized = useRef(false)

  useEffect(() => { saveSession(SESSION_KEY_TURNS, turns) }, [turns])
  useEffect(() => { saveSession(SESSION_KEY_BASE, baseLog) }, [baseLog])
  useEffect(() => { saveSession(SESSION_KEY_SID, currentSessionId) }, [currentSessionId])
  useEffect(() => { saveSession(SESSION_KEY_LID, currentLogId) }, [currentLogId])
  const abortRef = useRef<AbortController | null>(null)
  const pendingQueueRef = useRef<QueuedQuery[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Typewriter for the final-answer round only (rounds 0..N-1 are intermediate
  // thinking and render fully as they arrive, since they're collapsed).
  const CHARS_PER_TICK = 3
  const finalAnswerCursors = useRef<Map<string, number>>(new Map())
  const turnsRef = useRef<ConvTurn[]>(turns)
  const [, forceRender] = useState(0)

  useEffect(() => {
    turns.forEach(turn => {
      if (!turn.done) return
      const text = finalAnswerText(turn)
      if (text) finalAnswerCursors.current.set(turn.id, text.length)
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { turnsRef.current = turns }, [turns])

  useEffect(() => {
    const id = setInterval(() => {
      let anyBehind = false
      turnsRef.current.forEach(turn => {
        const text = finalAnswerText(turn)
        if (!text) return
        const cur = finalAnswerCursors.current.get(turn.id) ?? 0
        if (cur < text.length) {
          anyBehind = true
          finalAnswerCursors.current.set(turn.id, Math.min(cur + CHARS_PER_TICK, text.length))
        }
      })
      if (anyBehind) forceRender(n => n + 1)
    }, 16)
    return () => clearInterval(id)
  }, [])

  function getFinalDisplay(turn: ConvTurn): string {
    const text = finalAnswerText(turn)
    if (!text) return ''
    const cur = finalAnswerCursors.current.get(turn.id) ?? 0
    return text.slice(0, cur)
  }

  function resizeTextarea() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 20 * 3 + 22) + 'px'
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns.length])

  const confirm = useConfirm()
  const { data: logsData, refetch } = useQuery({
    queryKey: ['query-logs'],
    queryFn: () => fetchQueryLogs(50),
    staleTime: 0,
    refetchOnMount: true,
  })
  const logs = logsData?.logs ?? []

  // 首次加载后默认选中第一条历史记录
  useEffect(() => {
    if (!logsInitialized.current && logs.length > 0) {
      logsInitialized.current = true
      setSelectedLogId(logs[0].id)
    }
  }, [logs])

  const { data: logDetail } = useQuery({
    queryKey: ['query-log', selectedLogId],
    queryFn: () => fetchQueryLog(selectedLogId!),
    enabled: selectedLogId !== null,
    staleTime: 0,
  })

  async function runQueryInternal(q: string, sessionId: string | null) {
    setStreaming(true); setError(''); setSelectedLogId(null)

    const newTurnId = String(Date.now()) + Math.random().toString(36).slice(2)
    setTurns(prev => [...prev, {
      id: newTurnId, question: q, rounds: [], done: false, createdAt: Date.now(),
    }])

    abortRef.current = new AbortController()
    try {
      const res = await fetch('/query/agent', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, session_id: sessionId }),
        signal: abortRef.current.signal,
      })
      if (!res.ok) throw new Error(await res.text())
      const reader = res.body!.getReader(); const dec = new TextDecoder(); let buf = ''

      function updateTurn(updater: (t: ConvTurn) => ConvTurn) {
        setTurns(prev => prev.map(t => t.id === newTurnId ? updater(t) : t))
      }

      function ensureRound(turn: ConvTurn, roundNum: number): ConvTurn {
        if (turn.rounds.find(r => r.round === roundNum)) return turn
        return { ...turn, rounds: [...turn.rounds, { round: roundNum, thinking: '', toolCalls: [] }] }
      }

      function patchRound(turn: ConvTurn, roundNum: number, patch: (r: AgentRound) => AgentRound): ConvTurn {
        return { ...turn, rounds: turn.rounds.map(r => r.round === roundNum ? patch(r) : r) }
      }

      while (true) {
        const { done, value } = await reader.read(); if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const evt = JSON.parse(line) as Record<string, unknown>
            const et = String(evt.type)

            if (et === 'error') {
              setError(String(evt.message || t('query.err_unknown')))
            } else if (et === 'agent_start') {
              if (evt.session_id) setCurrentSessionId(evt.session_id as string)
            } else if (et === 'intent_check') {
              const intent = String(evt.intent || 'proceed')
              const message = String(evt.message || '')
              updateTurn(t => ({ ...t, intent, intentMessage: message }))
            } else if (et === 'round_start') {
              const r = Number(evt.round)
              updateTurn(t => ensureRound(t, r))
            } else if (et === 'delta') {
              const r = Number(evt.round)
              const chunk = String(evt.delta || '')
              if (!chunk) continue
              updateTurn(t => {
                const withRound = ensureRound(t, r)
                return patchRound(withRound, r, rd => ({ ...rd, thinking: rd.thinking + chunk }))
              })
            } else if (et === 'tool_call') {
              const r = Number(evt.round)
              const tc: AgentToolCall = {
                callId: String(evt.call_id || `${r}-${evt.tool}-${Math.random().toString(36).slice(2)}`),
                round: r,
                tool: String(evt.tool),
                args: (evt.args as Record<string, unknown>) || {},
              }
              updateTurn(t => {
                const withRound = ensureRound(t, r)
                return patchRound(withRound, r, rd => ({ ...rd, toolCalls: [...rd.toolCalls, tc] }))
              })
            } else if (et === 'tool_result') {
              const r = Number(evt.round)
              const callId = String(evt.call_id || '')
              updateTurn(t => patchRound(t, r, rd => ({
                ...rd,
                toolCalls: rd.toolCalls.map(tc => tc.callId === callId ? {
                  ...tc,
                  summary:   String(evt.summary || ''),
                  detail:    (evt.detail as ToolCallDetail | undefined) || undefined,
                  latencyMs: Number(evt.latency_ms ?? 0),
                } : tc),
              })))
            } else if (et === 'round_end') {
              const r = Number(evt.round)
              updateTurn(t => patchRound(t, r, rd => ({
                ...rd,
                finishReason: String(evt.finish_reason || ''),
                hadToolCalls: Boolean(evt.had_tool_calls),
              })))
            } else if (et === 'done') {
              if (evt.session_id) setCurrentSessionId(evt.session_id as string)
              const finalIdx = evt.final_round_index != null ? Number(evt.final_round_index) : undefined
              const newLogId = evt.log_id ? Number(evt.log_id) : null
              if (newLogId) {
                setCurrentLogId(newLogId)
                await qc.invalidateQueries({ queryKey: ['query-log', newLogId] })
              }
              updateTurn(t => ({ ...t, done: true, finalRoundIndex: finalIdx }))
              await refetch(); await qc.invalidateQueries({ queryKey: ['stats'] })
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (err) { if ((err as Error).name !== 'AbortError') setError(String(err)) }
    finally {
      setStreaming(false); abortRef.current = null
      setTurns(prev => prev.map(t => {
        if (t.id !== newTurnId) return t
        const updated = { ...t, done: true }
        return updated
      }))
      await refetch()
      const next = pendingQueueRef.current.shift()
      if (next) {
        setQueueLength(pendingQueueRef.current.length)
        await runQueryInternal(next.question, next.sessionId)
      } else {
        setQueueLength(0)
      }
    }
  }

  async function handleQuery() {
    const q = question.trim(); if (!q) return
    setQuestion('')
    if (textareaRef.current) { textareaRef.current.style.height = 'auto' }

    // 确定 session 上下文（入队时捕获，不在出队时再判断）
    let effectiveSessionId = currentSessionId
    if (selectedLogId && logDetail) {
      if (logDetail.session_id) effectiveSessionId = logDetail.session_id
      setBaseLog(logDetail)
      setCurrentSessionId(effectiveSessionId)
      setCurrentLogId(selectedLogId)
    }

    if (streaming) {
      pendingQueueRef.current.push({ question: q, sessionId: effectiveSessionId })
      setQueueLength(pendingQueueRef.current.length)
      return
    }

    await runQueryInternal(q, effectiveSessionId)
  }

  function handleNewConversation() {
    setTurns([]); setBaseLog(null); setCurrentSessionId(null); setCurrentLogId(null); setError(''); setSelectedLogId(null); clearSession()
    setQuestion('')
    if (textareaRef.current) { textareaRef.current.style.height = 'auto'; textareaRef.current.focus() }
  }

  async function handleClearLogs() {
    const ok = await confirm({ title: t('query.confirm_clear_title'), message: t('query.confirm_clear_msg'), confirmLabel: t('query.confirm_clear_btn'), danger: true })
    if (!ok) return
    await clearQueryLogs(); await refetch(); setSelectedLogId(null)
  }

  const showConversation = selectedLogId === null && (turns.length > 0 || streaming || baseLog !== null)
  const showHistoryDetail = selectedLogId !== null && !!logDetail
  const baseLogTurns = baseLog?.turns_json?.length ?? (baseLog ? 1 : 0)
  const doneTurns = turns.filter(t => t.done).length
  const totalTurns = baseLogTurns + doneTurns

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ── Main query area ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

        {/* Conversation thread */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>
          {error && (
            <div style={{ padding: '12px 16px', borderRadius: 10, marginBottom: 16, background: 'rgba(248,113,113,0.1)', border: '1px solid rgba(248,113,113,0.2)', color: '#f87171', fontSize: 12 }}>
              {error}
            </div>
          )}

          {/* 历史查询详情 */}
          {showHistoryDetail && (
            <div className="fade-in" style={{ maxWidth: 720 }}>
              <LogDetailView log={logDetail} />
            </div>
          )}

          {/* 空状态 */}
          {!showConversation && !error && !showHistoryDetail && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '60%', color: 'var(--text3)', gap: 10 }}>
              <Send size={28} strokeWidth={1.5} />
              <span style={{ fontSize: 13 }}>{t('query.empty_hint')}</span>
            </div>
          )}

          {/* 多轮对话 */}
          {showConversation && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 40, maxWidth: 720 }}>
              {/* 历史基底轮 */}
              {baseLog && (
                <div className="fade-in">
                  <LogDetailView log={baseLog} />
                  {turns.length > 0 && (
                    <div style={{ marginTop: 32, borderBottom: '1px dashed var(--border)', opacity: 0.5 }} />
                  )}
                </div>
              )}
              {turns.map((turn, ti) => {
                const isLast = ti === turns.length - 1
                const isOffTopic = turn.intent && turn.intent !== 'proceed'
                const finalIdx = effectiveFinalIndex(turn, isLast && streaming)
                const thinkingRounds = turn.rounds.filter(r => r.round !== finalIdx)
                const finalRound = finalIdx != null ? turn.rounds.find(r => r.round === finalIdx) : undefined
                const finalText = finalRound ? (turn.done ? getFinalDisplay(turn) : finalRound.thinking) : ''
                return (
                  <div key={turn.id} className="fade-in">
                    {/* user bubble */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'flex-end', gap: 8, marginBottom: 20 }}>
                      <span style={{ fontSize: 10, color: 'var(--text3)', flexShrink: 0 }}>{fmtTime(new Date(turn.createdAt).toISOString())}</span>
                      <div style={{
                        maxWidth: '80%', padding: '10px 16px', borderRadius: '16px 16px 4px 16px',
                        background: 'var(--accent)', color: '#fff', fontSize: 13, lineHeight: 1.6,
                      }}>
                        {turn.question}
                      </div>
                    </div>

                    {/* off-topic / clarify shortcut */}
                    {isOffTopic && (
                      <div style={{
                        display: 'inline-block', padding: '10px 16px', borderRadius: '4px 16px 16px 16px',
                        background: 'var(--surface2)', border: '1px solid var(--border2)',
                        fontSize: 13, color: 'var(--text)', lineHeight: 1.6,
                      }}>
                        {turn.intentMessage || ''}
                      </div>
                    )}

                    {/* normal proceed flow */}
                    {!isOffTopic && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                        {thinkingRounds.length > 0 && (
                          <ThinkingPanel
                            rounds={thinkingRounds}
                            streaming={isLast && streaming && !turn.done}
                          />
                        )}
                        {finalText && (
                          <MarkdownText text={finalText} />
                        )}
                        {isLast && streaming && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text3)', fontSize: 12 }}>
                            <span className="animate-pulse" style={{ color: 'var(--accent)' }}>●</span> {t('query.generating')}
                          </div>
                        )}
                      </div>
                    )}

                    {ti < turns.length - 1 && (
                      <div style={{ marginTop: 32, borderBottom: '1px dashed var(--border)', opacity: 0.5 }} />
                    )}
                  </div>
                )
              })}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Input bar */}
        <div style={{ padding: '14px 28px 20px', flexShrink: 0, borderTop: '1px solid var(--border)', background: 'var(--bg)' }}>
          {/* 追问/排队提示 */}
          {queueLength > 0 && (
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--accent2)' }}>{t('query.queue_n', { n: queueLength })}</span>
            </div>
          )}
          {totalTurns > 0 && !streaming && queueLength === 0 && (
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>
                {t('query.turn_n_followup', { n: totalTurns + 1 })}
              </span>
            </div>
          )}
          {selectedLogId && !streaming && turns.length === 0 && queueLength === 0 && (
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--accent2)' }}>
                {t('query.continue_session')}
              </span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
            <div style={{ flex: 1, position: 'relative' }}>
              <textarea ref={textareaRef} value={question}
                rows={1}
                onChange={e => { setQuestion(e.target.value); resizeTextarea() }}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleQuery() }
                }}
                placeholder={totalTurns > 0 ? t('query.placeholder_followup') : t('query.placeholder_initial')}
                className="input"
                style={{
                  paddingRight: 48, paddingTop: 11, paddingBottom: 11,
                  fontSize: 13, lineHeight: '20px', resize: 'none', overflow: 'hidden',
                  width: '100%', display: 'block',
                }}
              />
              <button onClick={streaming ? () => { abortRef.current?.abort(); pendingQueueRef.current = []; setQueueLength(0); setStreaming(false) } : handleQuery}
                disabled={!question.trim() && !streaming}
                style={{
                  position: 'absolute', right: 8, bottom: 8,
                  width: 32, height: 32, borderRadius: 8, border: 'none', cursor: 'pointer',
                  background: streaming ? 'rgba(248,113,113,0.15)' : 'var(--accent)',
                  color: streaming ? '#f87171' : '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  opacity: (!question.trim() && !streaming) ? 0.4 : 1,
                }}>
                {streaming ? <Square size={13} /> : <Send size={13} />}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── History sidebar ── */}
      <div style={{
        width: 280, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        background: 'var(--surface)', borderLeft: '1px solid var(--border)',
      }}>
        <div style={{ flexShrink: 0 }}>
          <button
            onClick={handleNewConversation}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
              width: '100%', padding: '10px 16px', border: 'none', borderBottom: '1px solid var(--border)',
              background: 'var(--accent)', cursor: 'pointer',
              fontSize: 12, fontWeight: 600, color: '#fff',
            }}
          >
            <MessageSquarePlus size={13} /> {t('query.new_chat')}
          </button>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Clock size={13} style={{ color: 'var(--text3)' }} />
              <span className="t-caption">{t('query.history_label')}</span>
            </div>
            {logs.length > 0 && (
              <button onClick={handleClearLogs} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', padding: 4, borderRadius: 6, color: 'var(--text3)' }}>
                <Trash2 size={13} />
              </button>
            )}
          </div>
        </div>

        {streaming && selectedLogId !== null && (
          <div
            onClick={() => setSelectedLogId(null)}
            style={{ cursor: 'pointer', padding: '8px 16px', background: 'rgba(99,102,241,0.1)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--accent2)', flexShrink: 0 }}
          >
            <span className="animate-pulse">●</span> {t('query.streaming_back')}
          </div>
        )}

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {logs.length === 0 && (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>{t('query.no_history')}</div>
          )}
          {logs.map(log => {
            const active = selectedLogId === log.id || (selectedLogId === null && log.id === currentLogId && (turns.length > 0 || streaming))
            return (
              <div key={log.id}
                onClick={() => {
                  // 点当前活跃的 log → 切回 live view
                  if (log.id === currentLogId && (turns.length > 0 || streaming)) {
                    setSelectedLogId(null)
                    return
                  }
                  setSelectedLogId(log.id === selectedLogId ? null : log.id)
                }}
                className="log-item"
                style={{
                  position: 'relative', padding: '12px 16px', cursor: 'pointer',
                  borderBottom: '1px solid var(--border)',
                  background: active ? 'rgba(99,102,241,0.13)' : 'transparent',
                  borderLeft: active ? '3px solid var(--accent)' : '3px solid transparent',
                  transition: 'background 0.15s, border-color 0.15s',
                  boxShadow: active ? 'inset 0 1px 0 rgba(99,102,241,0.15), inset 0 -1px 0 rgba(99,102,241,0.15)' : 'none',
                }}>
                <div style={{ paddingRight: 24 }}>
                  <div className="line-clamp-2" style={{ fontSize: 12, color: active ? 'var(--text)' : 'var(--text)', fontWeight: active ? 500 : 400, lineHeight: 1.5, marginBottom: 6 }}>{log.question}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: log.seeds.length ? 6 : 0 }}>
                    <span className="badge" style={{ background: 'rgba(99,102,241,0.12)', color: 'var(--accent2)' }}>{log.mode}</span>
                    {log.turn_count > 1 && <span className="badge" style={{ background: 'rgba(16,185,129,0.12)', color: '#10b981' }}>{t('query.turns_n', { n: log.turn_count })}</span>}
                    {log.id === currentLogId && streaming && (
                      <span className="animate-pulse" style={{ color: 'var(--accent)', fontSize: 10, lineHeight: 1 }}>●</span>
                    )}
                    <span style={{ fontSize: 10, color: 'var(--text3)' }}>{fmtTime(log.updated_at || log.created_at)}</span>
                  </div>
                  {log.seeds.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {log.seeds.slice(0, 4).map((s, i) => {
                        const color = getDomainColor(s.domain, backbones)
                        return <span key={i} className="chip" style={{ background: color + '22', color, fontSize: 10 }}>{s.label}</span>
                      })}
                    </div>
                  )}
                </div>
                <button
                  className="log-delete-btn"
                  onClick={async e => {
                    e.stopPropagation()
                    const ok = await confirm({ title: t('query.confirm_del_title'), message: t('query.confirm_del_msg'), confirmLabel: t('common.delete'), danger: true })
                    if (!ok) return
                    await deleteQueryLog(log.id)
                    if (selectedLogId === log.id) setSelectedLogId(null)
                    await refetch()
                  }}
                  style={{
                    position: 'absolute', top: 10, right: 10,
                    background: 'none', border: 'none', cursor: 'pointer',
                    padding: 4, borderRadius: 5, color: 'var(--text3)',
                    opacity: 0, transition: 'opacity 0.15s',
                    display: 'flex', alignItems: 'center',
                  }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            )
          })}
        </div>

      </div>
    </div>
  )
}

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g)
  return parts.map((part, j) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      return <strong key={j}>{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2)
      return <em key={j}>{part.slice(1, -1)}</em>
    return part
  })
}

function MarkdownText({ text, style }: { text: string; style?: React.CSSProperties }) {
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.startsWith('### ')) {
      elements.push(<div key={i} style={{ fontWeight: 700, fontSize: 13, marginTop: 14, marginBottom: 2 }}>{renderInline(line.slice(4))}</div>)
    } else if (line.startsWith('## ')) {
      elements.push(<div key={i} style={{ fontWeight: 700, fontSize: 14, marginTop: 18, marginBottom: 4 }}>{renderInline(line.slice(3))}</div>)
    } else if (line.startsWith('# ')) {
      elements.push(<div key={i} style={{ fontWeight: 700, fontSize: 15, marginTop: 20, marginBottom: 6 }}>{renderInline(line.slice(2))}</div>)
    } else if (/^[-*] /.test(line)) {
      elements.push(
        <div key={i} style={{ display: 'flex', gap: 8, lineHeight: 1.75 }}>
          <span style={{ color: 'var(--accent2)', flexShrink: 0, userSelect: 'none' }}>·</span>
          <span>{renderInline(line.slice(2))}</span>
        </div>
      )
    } else if (line === '') {
      elements.push(<div key={i} style={{ height: '0.5em' }} />)
    } else {
      elements.push(<div key={i} style={{ lineHeight: 1.75 }}>{renderInline(line)}</div>)
    }
  }
  return <div style={{ fontSize: 13, color: 'var(--text)', ...style }}>{elements}</div>
}

// ── Agent-mode helpers ──────────────────────────────────────────────────────

function finalAnswerText(turn: ConvTurn): string {
  if (turn.intent && turn.intent !== 'proceed') return turn.intentMessage || ''
  const idx = effectiveFinalIndex(turn, false)
  if (idx == null) return ''
  const r = turn.rounds.find(rr => rr.round === idx)
  return r?.thinking || ''
}

function effectiveFinalIndex(turn: ConvTurn, isStreamingNow: boolean): number | undefined {
  if (turn.finalRoundIndex != null) return turn.finalRoundIndex
  if (!turn.rounds.length) return undefined
  // Mid-stream: tentatively treat the last round with no tool_calls as the answer.
  // While streaming we don't yet know — show no final until round_end clarifies.
  if (isStreamingNow) {
    for (let i = turn.rounds.length - 1; i >= 0; i--) {
      const r = turn.rounds[i]
      if (r.finishReason && !r.hadToolCalls) return r.round
    }
    return undefined
  }
  // After done: pick the last round that had no tool_calls
  for (let i = turn.rounds.length - 1; i >= 0; i--) {
    const r = turn.rounds[i]
    if (!r.hadToolCalls) return r.round
  }
  return turn.rounds[turn.rounds.length - 1].round
}

function ThinkingPanel({ rounds, streaming }: { rounds: AgentRound[]; streaming: boolean }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(streaming)
  // auto-open while streaming, auto-collapse once we have the final answer
  useEffect(() => { if (streaming) setOpen(true) }, [streaming])
  const totalCalls = rounds.reduce((s, r) => s + r.toolCalls.length, 0)
  return (
    <div style={{ borderRadius: 10, border: '1px solid var(--border2)', overflow: 'hidden', fontSize: 12 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          width: '100%', padding: '8px 14px', background: 'var(--surface2)',
          border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
          color: 'var(--text)', textAlign: 'left',
        }}
      >
        <span style={{ color: 'var(--accent2)' }}>{open ? '▾' : '▸'}</span>
        <span style={{ fontWeight: 600 }}>{t('query.thinking')}</span>
        <span style={{ color: 'var(--text3)', fontSize: 11 }}>
          {t('query.thinking_meta', { rounds: rounds.length, calls: totalCalls })}
        </span>
        {streaming && (
          <span className="animate-pulse" style={{ marginLeft: 'auto', color: 'var(--accent)', fontSize: 10 }}>●</span>
        )}
      </button>
      {open && (
        <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 16, borderTop: '1px solid var(--border2)' }}>
          {rounds.map(r => (
            <div key={r.round}>
              <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                {t('query.round_n', { n: r.round })}
              </div>
              {r.thinking && (
                <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.65, whiteSpace: 'pre-wrap', marginBottom: r.toolCalls.length ? 8 : 0 }}>
                  {r.thinking}
                </div>
              )}
              {r.toolCalls.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {r.toolCalls.map(tc => <AgentToolCallRow key={tc.callId} tc={tc} />)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function AgentToolCallRow({ tc }: { tc: AgentToolCall }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const label = TOOL_LABEL_KEYS[tc.tool] ? t(TOOL_LABEL_KEYS[tc.tool] as Parameters<typeof t>[0]) : tc.tool
  const color = TOOL_COLORS[tc.tool] || '#94a3b8'
  const argText = Object.entries(tc.args)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}`)
    .join(', ')
  const hasDetail = tc.detail && Object.keys(tc.detail).length > 0
  return (
    <div style={{
      borderRadius: 8, border: '1px solid var(--border2)',
      background: 'var(--surface)', overflow: 'hidden', fontSize: 12,
      borderLeft: `3px solid ${color}`,
    }}>
      <div
        onClick={() => hasDetail && setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px',
          cursor: hasDetail ? 'pointer' : 'default', userSelect: 'none', flexWrap: 'wrap',
        }}
      >
        <span style={{ color, fontWeight: 600 }}>{label}</span>
        <span style={{ color: 'var(--text3)', fontFamily: 'monospace', fontSize: 11 }}>({argText})</span>
        {tc.summary ? (
          <span style={{ flex: 1, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 80 }}>
            → {tc.summary}
          </span>
        ) : (
          <span style={{ flex: 1, color: 'var(--text3)', fontStyle: 'italic' }}>{t('query.tool_running')}</span>
        )}
        {tc.latencyMs != null && tc.latencyMs > 0 && (
          <span style={{ color: 'var(--text3)', fontSize: 10, flexShrink: 0 }}>{tc.latencyMs}ms</span>
        )}
        {hasDetail && (
          <span style={{ color: 'var(--text3)', flexShrink: 0 }}>{open ? '▲' : '▼'}</span>
        )}
      </div>
      {open && hasDetail && tc.detail && (
        <ToolDetailRender detail={tc.detail} />
      )}
    </div>
  )
}

function ToolDetailRender({ detail }: { detail: ToolCallDetail }) {
  const { backbones } = useBackbones()
  const { lang, t } = useI18n()
  const nodes = (detail.nodes as NodeDetail[] | undefined) || []
  const edges = (detail.edges as EdgeDetail[] | undefined) || []
  const blindspots = (detail.blindspots as NodeDetail[] | undefined) || []
  const opposites = (detail.opposites as NodeDetail[] | undefined) || []
  const bridges = (detail.bridges as Array<Record<string, unknown>> | undefined) || []
  const paths = (detail.paths as Array<Record<string, unknown>> | undefined) || []
  const entries = (detail.entries as Array<Record<string, unknown>> | undefined) || []
  const results = (detail.results as Array<Record<string, unknown>> | undefined) || []
  const text = typeof detail.text === 'string' ? detail.text : ''

  const allNodes = [...nodes, ...blindspots, ...opposites]

  return (
    <div style={{ borderTop: '1px solid var(--border2)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
      {allNodes.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{t('query.nodes')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {allNodes.map((n, i) => {
              const color = getDomainColor(n.domain, backbones)
              return (
                <div key={i} style={{ padding: '6px 8px', borderRadius: 6, background: 'var(--surface2)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text)', fontSize: 11 }}>{n.label}</span>
                    <span className="badge" style={{ background: color + '22', color, fontSize: 10 }}>{getDomainLabel(n.domain, backbones, lang)}</span>
                    <span style={{ color: n.origin === 'internal' ? 'var(--accent2)' : 'var(--text3)', fontSize: 10 }}>
                      {n.origin === 'internal' ? t('query.origin_internal') : t('query.origin_external')}
                    </span>
                    <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 10 }}>
                      str {typeof n.strength === 'number' ? n.strength.toFixed(2) : n.strength}
                      {n.sim != null ? ` · sim ${typeof n.sim === 'number' ? n.sim.toFixed(3) : n.sim}` : ''}
                    </span>
                  </div>
                  {n.description && (
                    <div style={{ marginTop: 3, fontSize: 10, color: 'var(--text3)', lineHeight: 1.5 }}>{n.description}</div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {edges.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{t('query.edges')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {edges.map((e, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text2)', fontSize: 11 }}>
                <span style={{ color: 'var(--text)' }}>{e.from_label}</span>
                <span style={{ color: 'var(--accent2)', fontWeight: 500 }}>—{e.relation_type}→</span>
                <span style={{ color: 'var(--text)' }}>{e.to_label}</span>
                <span style={{ color: 'var(--text3)', marginLeft: 'auto' }}>{typeof e.weight === 'number' ? e.weight.toFixed(3) : e.weight}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {bridges.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{t('query.bridges')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {bridges.map((b, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--text2)' }}>
                [{String(b.from_origin)}] {String(b.from_label)} —{String(b.relation_type)}→ [{String(b.to_origin)}] {String(b.to_label)}
                <span style={{ color: 'var(--text3)', marginLeft: 6 }}>w={typeof b.weight === 'number' ? b.weight.toFixed(2) : String(b.weight ?? '')}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {paths.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{t('query.paths')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {paths.map((p, i) => {
              const hops = (p.hops as Array<Record<string, unknown>> | undefined) || []
              return (
                <div key={i} style={{ fontSize: 11, color: 'var(--text2)' }}>
                  <span style={{ color: 'var(--accent2)' }}>{String(p.anchor_label)}</span>
                  {hops.map((h, j) => (
                    <span key={j}> →{String(h.relation)}→ <span style={{ color: 'var(--text)' }}>{String(h.to_label)}</span></span>
                  ))}
                  <span style={{ color: 'var(--text3)', marginLeft: 6 }}>score={String(p.score)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
      {entries.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{t('query.raw_records_n', { n: entries.length })}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {entries.map((e, i) => (
              <div key={i} style={{ borderLeft: '2px solid var(--accent2)', paddingLeft: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 3 }}>#{String(e.id)} · {String(e.date)}</div>
                <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{String(e.raw)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {results.length > 0 && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{t('query.web_results')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {results.map((r, i) => (
              <div key={i} style={{ fontSize: 11 }}>
                <a href={String(r.url || '')} target="_blank" rel="noreferrer" style={{ color: 'var(--accent2)', fontWeight: 600 }}>
                  {String(r.title || r.url || '(untitled)')}
                </a>
                {r.snippet ? <div style={{ color: 'var(--text3)', marginTop: 2 }}>{String(r.snippet)}</div> : null}
              </div>
            ))}
          </div>
        </div>
      )}
      {text && (
        <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.65, whiteSpace: 'pre-wrap', padding: 6, background: 'var(--surface2)', borderRadius: 4 }}>
          {text}
        </div>
      )}
    </div>
  )
}

function HistoryContextBlock({ text }: { text: string }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  return (
    <div style={{ marginBottom: 12, borderRadius: 8, border: '1px solid var(--border2)', overflow: 'hidden', fontSize: 12 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{ width: '100%', padding: '6px 12px', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text3)', fontSize: 11, textAlign: 'left' }}
      >
        <span style={{ color: 'var(--accent2)' }}>{open ? '▲' : '▼'}</span>
        {t('query.inject_history')}
      </button>
      {open && (
        <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border2)', background: 'var(--surface)', color: 'var(--text2)', whiteSpace: 'pre-wrap', lineHeight: 1.65, fontSize: 11 }}>
          {text}
        </div>
      )}
    </div>
  )
}

function buildLogMarkdown(log: QueryLogDetail): string {
  const turns: QueryTurn[] = log.turns_json?.length
    ? log.turns_json
    : [{
        question: log.question,
        intent: 'proceed',
        response: log.q3_text || '',
        q1_text: log.q1_text || undefined,
        q2_text: log.q2_text || undefined,
        created_at: log.created_at,
      }]

  const out: string[] = []
  out.push(`# Engram Query Log #${log.id}`)
  out.push('')
  out.push(`- **Session**: ${log.session_id || '—'}`)
  out.push(`- **Created**: ${log.created_at}`)
  out.push(`- **Updated**: ${log.updated_at}`)
  out.push(`- **Mode**: ${log.mode || '—'}`)
  out.push(`- **Turns**: ${turns.length}`)
  if (log.seeds?.length) {
    out.push(`- **Seed nodes**: ${log.seeds.map(s => `${s.label}（${s.domain}）`).join('、')}`)
  }
  out.push('')
  out.push('---')
  out.push('')

  turns.forEach((t, i) => {
    out.push(`## Turn ${i + 1} · ${t.created_at}`)
    out.push('')
    out.push(`**Q**: ${t.question}`)
    out.push('')
    if (t.mode) out.push(`**Mode**: ${t.mode}`)
    out.push(`**Intent**: ${t.intent}`)
    out.push('')

    if (t.history_context) {
      out.push('### History context')
      out.push('```')
      out.push(t.history_context)
      out.push('```')
      out.push('')
    }

    if (t.q1_text) {
      out.push('### Q1 Baseline')
      out.push(t.q1_text)
      out.push('')
    }

    if (t.q2_text) {
      out.push('### Q2 Persona')
      out.push(t.q2_text)
      out.push('')
    }

    if (t.tool_calls?.length) {
      out.push('### Agent tool calls')
      t.tool_calls.forEach(c => {
        const argText = Object.entries(c.args || {})
          .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}`)
          .join(', ')
        out.push(`- **R${c.round} · ${c.tool}** (${argText})`)
        if (c.summary) out.push(`  - summary: ${c.summary}`)
        if (c.preview) {
          out.push('  - preview:')
          out.push('    ```')
          c.preview.split('\n').forEach(line => out.push(`    ${line}`))
          out.push('    ```')
        }
      })
      out.push('')
    }

    if (t.theme_recall?.length) {
      out.push('### Raw recall (evidence used by synthesis)')
      t.theme_recall.forEach(r => {
        out.push(`#### 「${r.node_label}」（${r.node_domain}, strength=${r.strength.toFixed(3)}）`)
        r.entries.forEach(e => {
          out.push(`- [${e.date}] **#${e.id}**: ${e.raw}`)
        })
        out.push('')
      })
    }

    if (t.response) {
      out.push('### Q3 Graph insight (synthesis)')
      out.push(t.response)
      out.push('')
    }

    if (i < turns.length - 1) {
      out.push('---')
      out.push('')
    }
  })

  if (log.q4_text) {
    out.push('---')
    out.push('')
    out.push('## Q4 Theme deep-dive (combined)')
    out.push(log.q4_text)
    out.push('')
  }

  return out.join('\n')
}

function downloadLog(log: QueryLogDetail) {
  const md = buildLogMarkdown(log)
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const stamp = (log.updated_at || log.created_at || '').replace(/[:.]/g, '-').slice(0, 19)
  a.download = `engram-query-${log.id}-${stamp}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function copyLog(log: QueryLogDetail) {
  try {
    await navigator.clipboard.writeText(buildLogMarkdown(log))
  } catch {
    // ignore
  }
}

function LogDetailView({ log }: { log: QueryLogDetail }) {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)
  const turns: QueryTurn[] = log.turns_json?.length
    ? log.turns_json
    : [{
        question: log.question,
        intent: 'proceed',
        response: log.q3_text || '',
        q1_text: log.q1_text || undefined,
        q2_text: log.q2_text || undefined,
        created_at: log.created_at,
      }]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginBottom: -16 }}>
        <button
          onClick={async () => { await copyLog(log); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
          style={{
            padding: '4px 12px', borderRadius: 6, border: '1px solid var(--border2)',
            background: 'transparent', color: 'var(--text3)', fontSize: 11, cursor: 'pointer',
          }}>
          {copied ? t('query.copied') : t('query.copy_md')}
        </button>
        <button
          onClick={() => downloadLog(log)}
          style={{
            padding: '4px 12px', borderRadius: 6, border: '1px solid var(--border2)',
            background: 'transparent', color: 'var(--text3)', fontSize: 11, cursor: 'pointer',
          }}>
          {t('query.download_md')}
        </button>
      </div>
      {turns.map((turn, i) => (
        <div key={i}>
          {/* 问题气泡 */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'flex-end', gap: 8, marginBottom: 16 }}>
            <span style={{ fontSize: 10, color: 'var(--text3)', flexShrink: 0 }}>{fmtTime(turn.created_at)}</span>
            <div style={{ maxWidth: '80%', padding: '10px 16px', borderRadius: '16px 16px 4px 16px', background: 'var(--accent)', color: '#fff', fontSize: 13, lineHeight: 1.6 }}>
              {turn.question}
            </div>
          </div>
          {/* 历史上下文（可折叠） */}
          {turn.history_context && (
            <HistoryContextBlock text={turn.history_context} />
          )}
          {/* 回复 */}
          {turn.intent === 'proceed' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {turn.q1_text && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>{t('query.section_baseline')}</div>
                  <MarkdownText text={turn.q1_text} />
                </div>
              )}
              {turn.q2_text && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>{t('query.section_persona')}</div>
                  <MarkdownText text={turn.q2_text} />
                </div>
              )}
              {turn.tool_calls && turn.tool_calls.length > 0 && (
                <ToolTraceBlock calls={turn.tool_calls} />
              )}
              {turn.theme_recall && turn.theme_recall.length > 0 && (
                <ThemeRecallBlock items={turn.theme_recall} />
              )}
              {turn.response && (
                <div>
                  {(turn.q1_text || turn.q2_text) && (
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                      {t('query.section_synthesis')}{turn.mode && <span style={{ fontWeight: 400, color: 'var(--text3)', marginLeft: 6 }}>· {turn.mode}</span>}
                    </div>
                  )}
                  <MarkdownText text={turn.response} />
                </div>
              )}
            </div>
          ) : (
            <div style={{ display: 'inline-block', padding: '10px 16px', borderRadius: '4px 16px 16px 16px', background: 'var(--surface2)', border: '1px solid var(--border2)', fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
              {turn.response}
            </div>
          )}
          {i < turns.length - 1 && (
            <div style={{ marginTop: 24, borderBottom: '1px dashed var(--border)', opacity: 0.4 }} />
          )}
        </div>
      ))}
    </div>
  )
}

const TRACE_TOOL_META: Record<string, { labelKey: string; color: string }> = {
  graph_search:  { labelKey: 'query.tool_label_search',   color: '#6366f1' },
  expand_node:   { labelKey: 'query.tool_label_expand',   color: '#10b981' },
  get_opposites: { labelKey: 'query.tool_label_opposite', color: '#f87171' },
  web_search:    { labelKey: 'query.tool_label_web',      color: '#f59e0b' },
}

function ToolTraceBlock({ calls }: { calls: ToolCallTrace[] }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  return (
    <div>
      <div
        onClick={() => setOpen(v => !v)}
        style={{
          fontSize: 11, fontWeight: 600, color: 'var(--accent2)',
          textTransform: 'uppercase', letterSpacing: '0.05em',
          cursor: 'pointer', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6,
        }}>
        {t('query.agent_log', { n: calls.length })} {open ? '▾' : '▸'}
      </div>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingLeft: 4 }}>
          {calls.map((c, i) => {
            const meta = TRACE_TOOL_META[c.tool]
            const label = meta ? t(meta.labelKey as Parameters<typeof t>[0]) : c.tool
            const color = meta ? meta.color : '#94a3b8'
            const argText = Object.entries(c.args || {})
              .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}`)
              .join(', ')
            return (
              <div key={i} style={{
                padding: '8px 12px', borderRadius: 8,
                background: 'var(--surface2)', borderLeft: `3px solid ${color}`,
                fontSize: 11,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ color, fontWeight: 600 }}>R{c.round}</span>
                  <span style={{ color: 'var(--text)', fontWeight: 600 }}>{label}</span>
                  <span style={{ color: 'var(--text3)', fontFamily: 'monospace' }}>({argText})</span>
                </div>
                {c.summary && (
                  <div style={{ color: 'var(--text3)', marginBottom: 4 }}>{c.summary}</div>
                )}
                {c.preview && (
                  <details style={{ cursor: 'pointer' }}>
                    <summary style={{ fontSize: 10, color: 'var(--text3)' }}>{t('query.expand_payload')}</summary>
                    <pre style={{
                      fontSize: 10, color: 'var(--text2)', whiteSpace: 'pre-wrap',
                      marginTop: 6, padding: '6px 8px', background: 'var(--surface)',
                      borderRadius: 4, maxHeight: 240, overflowY: 'auto',
                    }}>{c.preview}</pre>
                  </details>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function ThemeRecallBlock({ items }: { items: ThemeRecall[] }) {
  const { backbones } = useBackbones()
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const totalEntries = items.reduce((s, t) => s + t.entries.length, 0)
  return (
    <div>
      <div
        onClick={() => setOpen(v => !v)}
        style={{
          fontSize: 11, fontWeight: 600, color: 'var(--accent2)',
          textTransform: 'uppercase', letterSpacing: '0.05em',
          cursor: 'pointer', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6,
        }}>
        {t('query.raw_recall_n', { n: items.length, entries: totalEntries })} {open ? '▾' : '▸'}
      </div>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map((t, i) => {
            const color = getDomainColor(t.node_domain, backbones)
            return (
              <div key={i} style={{
                padding: '10px 12px', borderRadius: 8,
                background: 'var(--surface2)', borderLeft: `3px solid ${color}`,
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>
                  「{t.node_label}」
                  <span style={{ color: 'var(--text3)', fontWeight: 400, marginLeft: 6, fontSize: 10 }}>
                    {t.node_domain} · strength {t.strength.toFixed(3)}
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {t.entries.map((e, j) => (
                    <div key={j} style={{
                      fontSize: 11, color: 'var(--text2)', lineHeight: 1.5,
                      padding: '4px 8px', borderLeft: '2px solid var(--border)',
                    }}>
                      <span style={{ color: 'var(--text3)', fontSize: 10, marginRight: 6 }}>[{e.date}] #{e.id}</span>
                      {e.raw}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
