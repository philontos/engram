import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchQueryLogs, fetchQueryLog, clearQueryLogs, deleteQueryLog } from '@/api'
import type { QueryLogDetail, QueryTurn } from '@/types'
import { DOMAIN_COLORS } from '@/lib/constants'
import { fmtTime } from '@/lib/utils'
import { Send, Square, Trash2, Clock, MessageSquarePlus } from 'lucide-react'
import { useConfirm } from '@/components/ui/ConfirmDialog'

type NodeDetail = { id: number; label: string; domain: string; origin: string; strength: number; sim?: number | null; description?: string }
type EdgeDetail = { from_label: string; relation_type: string; to_label: string; weight: number }
type ToolCallDetail = { nodes: NodeDetail[]; edges: EdgeDetail[] }
type ToolCall = { round: number; tool: string; args: Record<string, unknown>; summary?: string; node_count?: number; detail?: ToolCallDetail }
type ThemeEntry = { id: number; date: string; raw: string }
type ThemeNode = { id: number; label: string; domain: string; node_type: string; origin: string; strength: number; description?: string }
type ThemeResult = { node: ThemeNode; entries: ThemeEntry[]; analysis: string }
type StreamPhase = { stage: string; text: string; toolCalls?: ToolCall[]; themeResults?: ThemeResult[] }
type ConvTurn = { id: string; question: string; phases: StreamPhase[]; done: boolean; createdAt: number }
type QueuedQuery = { question: string; mode: 'full' | 'fast'; sessionId: string | null }

const SESSION_KEY_TURNS   = 'query_turns'
const SESSION_KEY_BASE    = 'query_base_log'
const SESSION_KEY_SID     = 'query_session_id'
const SESSION_KEY_LID     = 'query_log_id'

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

const STAGE_LABELS: Record<string, string> = {
  intent_check:      '意图识别',
  baseline:          '通用解答',
  persona_blindspot: '人格穿刺',
  graph_explore:     '图谱探索',
  theme_analysis:    '主题深析',
  graph_insight:     '图谱洞察',
}

const INLINE_STAGES = new Set(['intent_check'])

const TOOL_LABELS: Record<string, string> = {
  graph_search:  '语义搜索',
  expand_node:   '展开子图',
  get_opposites: '寻找对立',
}


export function QueryTab() {
  const qc = useQueryClient()
  const [question, setQuestion] = useState('')
  const [mode, setMode]         = useState<'full' | 'fast'>('full')
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

  // 打字机效果：用 ref 存完整文本，interval 每帧推进 cursor
  const CHARS_PER_TICK = 3
  const displayCursors = useRef<Map<string, number>>(new Map())
  const turnsRef = useRef<ConvTurn[]>(turns)
  const [, forceRender] = useState(0)

  // 初始化时把已完成的 turns cursor 直接设到末尾，避免历史记录重放打字机
  useEffect(() => {
    turns.forEach((turn, ti) => {
      if (!turn.done) return
      turn.phases.forEach((phase, pi) => {
        if (!phase.text) return
        displayCursors.current.set(`${ti}-${pi}`, phase.text.length)
      })
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 同步 turnsRef，避免 interval 闭包过期
  useEffect(() => { turnsRef.current = turns }, [turns])

  // interval 只挂载一次，读 turnsRef 避免重建
  useEffect(() => {
    const id = setInterval(() => {
      let anyBehind = false
      turnsRef.current.forEach((turn, ti) => {
        turn.phases.forEach((phase, pi) => {
          if (!phase.text) return
          const key = `${ti}-${pi}`
          const cur = displayCursors.current.get(key) ?? 0
          if (cur < phase.text.length) {
            anyBehind = true
            displayCursors.current.set(key, Math.min(cur + CHARS_PER_TICK, phase.text.length))
          }
        })
      })
      if (anyBehind) forceRender(n => n + 1)
    }, 16)
    return () => clearInterval(id)
  }, []) // 只挂载一次

  function getDisplayText(ti: number, pi: number, fullText: string): string {
    const key = `${ti}-${pi}`
    const cur = displayCursors.current.get(key) ?? 0
    return fullText.slice(0, cur)
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

  async function runQueryInternal(q: string, qMode: 'full' | 'fast', sessionId: string | null) {
    setStreaming(true); setError(''); setSelectedLogId(null)

    const newTurnId = String(Date.now()) + Math.random().toString(36).slice(2)
    setTurns(prev => [...prev, { id: newTurnId, question: q, phases: [], done: false, createdAt: Date.now() }])

    abortRef.current = new AbortController()
    try {
      const res = await fetch('/query', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, mode: qMode, session_id: sessionId }),
        signal: abortRef.current.signal,
      })
      if (!res.ok) throw new Error(await res.text())
      const reader = res.body!.getReader(); const dec = new TextDecoder(); let buf = ''

      function updateTurn(updater: (t: ConvTurn) => ConvTurn) {
        setTurns(prev => prev.map(t => t.id === newTurnId ? updater(t) : t))
      }

      while (true) {
        const { done, value } = await reader.read(); if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const evt = JSON.parse(line) as Record<string, unknown>
            if (evt.type === 'error') {
              setError(String(evt.message || '未知错误'))
            } else if (evt.type === 'stage' && evt.status === 'start') {
              updateTurn(t => ({ ...t, phases: [...t.phases, { stage: String(evt.stage || ''), text: '', toolCalls: [] }] }))
            } else if (evt.type === 'delta') {
              const chunk = String(evt.delta || ''); if (!chunk) continue
              updateTurn(t => {
                if (!t.phases.length) return { ...t, phases: [{ stage: '', text: chunk }] }
                const ps = [...t.phases]; ps[ps.length - 1] = { ...ps[ps.length - 1], text: ps[ps.length - 1].text + chunk }
                return { ...t, phases: ps }
              })
            } else if (evt.type === 'tool_call') {
              const tc: ToolCall = { round: Number(evt.round), tool: String(evt.tool), args: (evt.args as Record<string, unknown>) || {} }
              updateTurn(t => {
                if (!t.phases.length) return t
                const ps = [...t.phases]; const last = { ...ps[ps.length - 1] }
                last.toolCalls = [...(last.toolCalls || []), tc]; ps[ps.length - 1] = last
                return { ...t, phases: ps }
              })
            } else if (evt.type === 'tool_result') {
              updateTurn(t => {
                if (!t.phases.length) return t
                const ps = [...t.phases]; const last = { ...ps[ps.length - 1] }
                const tcs = [...(last.toolCalls || [])]
                const idx = tcs.findLastIndex(tc => tc.tool === String(evt.tool) && tc.round === Number(evt.round) && !tc.summary)
                if (idx !== -1) tcs[idx] = { ...tcs[idx], summary: String(evt.summary || ''), node_count: Number(evt.node_count ?? 0), detail: evt.detail as ToolCallDetail | undefined }
                last.toolCalls = tcs; ps[ps.length - 1] = last
                return { ...t, phases: ps }
              })
            } else if (evt.type === 'theme_result') {
              const tr = evt as unknown as { type: string } & ThemeResult
              updateTurn(t => {
                if (!t.phases.length) return t
                const ps = [...t.phases]; const last = { ...ps[ps.length - 1] }
                last.themeResults = [...(last.themeResults || []), { node: tr.node, entries: tr.entries, analysis: tr.analysis }]
                ps[ps.length - 1] = last
                return { ...t, phases: ps }
              })
            } else if (evt.type === 'done' || evt.type === 'complete') {
              if (evt.session_id) setCurrentSessionId(evt.session_id as string)
              const newLogId = evt.log_id ? Number(evt.log_id) : null
              if (newLogId) {
                setCurrentLogId(newLogId)
                await qc.invalidateQueries({ queryKey: ['query-log', newLogId] })
              }
              updateTurn(t => ({ ...t, done: true }))
              await refetch(); await qc.invalidateQueries({ queryKey: ['stats'] })
            }
          } catch { /* skip */ }
        }
      }
    } catch (err) { if ((err as Error).name !== 'AbortError') setError(String(err)) }
    finally {
      setStreaming(false); abortRef.current = null
      setTurns(prev => prev.map((t, idx) => {
        if (t.id !== newTurnId) return t
        const updated = { ...t, done: true }
        updated.phases.forEach((phase, pi) => {
          if (phase.text) displayCursors.current.set(`${idx}-${pi}`, phase.text.length)
        })
        return updated
      }))
      await refetch()
      // 出队执行下一个
      const next = pendingQueueRef.current.shift()
      if (next) {
        setQueueLength(pendingQueueRef.current.length)
        await runQueryInternal(next.question, next.mode, next.sessionId)
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
      pendingQueueRef.current.push({ question: q, mode, sessionId: effectiveSessionId })
      setQueueLength(pendingQueueRef.current.length)
      return
    }

    await runQueryInternal(q, mode, effectiveSessionId)
  }

  function handleNewConversation() {
    setTurns([]); setBaseLog(null); setCurrentSessionId(null); setCurrentLogId(null); setError(''); setSelectedLogId(null); clearSession()
    setQuestion('')
    if (textareaRef.current) { textareaRef.current.style.height = 'auto'; textareaRef.current.focus() }
  }

  async function handleClearLogs() {
    const ok = await confirm({ title: '清除查询历史', message: '所有历史记录将被永久删除。', confirmLabel: '清除', danger: true })
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
              <span style={{ fontSize: 13 }}>输入问题开始探索你的认知图谱</span>
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
              {turns.map((turn, ti) => (
                <div key={ti} className="fade-in">
                  {/* 用户问题气泡 */}
                  <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'flex-end', gap: 8, marginBottom: 20 }}>
                    <span style={{ fontSize: 10, color: 'var(--text3)', flexShrink: 0 }}>{fmtTime(new Date(turn.createdAt).toISOString())}</span>
                    <div style={{
                      maxWidth: '80%', padding: '10px 16px', borderRadius: '16px 16px 4px 16px',
                      background: 'var(--accent)', color: '#fff', fontSize: 13, lineHeight: 1.6,
                    }}>
                      {turn.question}
                    </div>
                  </div>
                  {/* 阶段输出 */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                    {turn.phases.map((p, i) => (
                      <div key={i}>
                        {p.stage && !INLINE_STAGES.has(p.stage) && (
                          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                            {STAGE_LABELS[p.stage] ?? p.stage}
                          </div>
                        )}
                        {p.toolCalls && p.toolCalls.length > 0 && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: (p.themeResults?.length || p.text) ? 16 : 0 }}>
                            {p.toolCalls.map((tc, j) => <ToolCallRow key={j} tc={tc} />)}
                          </div>
                        )}
                        {p.themeResults && p.themeResults.length > 0 && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                            {p.themeResults.map((tr, j) => <ThemeResultCard key={j} result={tr} />)}
                          </div>
                        )}
                        {p.text && INLINE_STAGES.has(p.stage) && (
                          <div style={{
                            display: 'inline-block', padding: '10px 16px', borderRadius: '4px 16px 16px 16px',
                            background: 'var(--surface2)', border: '1px solid var(--border2)',
                            fontSize: 13, color: 'var(--text)', lineHeight: 1.6,
                          }}>{getDisplayText(ti, i, p.text)}</div>
                        )}
                        {p.text && !INLINE_STAGES.has(p.stage) && p.stage !== 'theme_analysis' && (
                          <MarkdownText text={getDisplayText(ti, i, p.text)} />
                        )}
                        {p.text && p.stage === 'theme_analysis' && !p.themeResults?.length && (
                          <MarkdownText text={getDisplayText(ti, i, p.text)} />
                        )}
                      </div>
                    ))}
                    {/* 最后一轮流式指示器 */}
                    {ti === turns.length - 1 && streaming && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text3)', fontSize: 12 }}>
                        <span className="animate-pulse" style={{ color: 'var(--accent)' }}>●</span> 生成中…
                      </div>
                    )}
                  </div>
                  {/* 轮次分隔 */}
                  {ti < turns.length - 1 && (
                    <div style={{ marginTop: 32, borderBottom: '1px dashed var(--border)', opacity: 0.5 }} />
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Input bar */}
        <div style={{ padding: '14px 28px 20px', flexShrink: 0, borderTop: '1px solid var(--border)', background: 'var(--bg)' }}>
          {/* 追问/排队提示 */}
          {queueLength > 0 && (
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--accent2)' }}>已排队 {queueLength} 个问题</span>
            </div>
          )}
          {totalTurns > 0 && !streaming && queueLength === 0 && (
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>
                第 {totalTurns + 1} 轮 · 可继续追问，上下文已自动携带
              </span>
            </div>
          )}
          {selectedLogId && !streaming && turns.length === 0 && queueLength === 0 && (
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--accent2)' }}>
                继续此对话 · 发送后延续历史上下文
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
                placeholder={totalTurns > 0 ? '继续追问…' : '输入问题，对你的认知图谱发起查询…'}
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
            <div style={{ display: 'flex', background: 'var(--surface2)', borderRadius: 8, border: '1px solid var(--border2)', overflow: 'hidden', marginBottom: 1 }}>
              {(['full', 'fast'] as const).map(m => (
                <button key={m} onClick={() => setMode(m)}
                  style={{
                    padding: '8px 14px', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500,
                    background: mode === m ? 'var(--accent)' : 'transparent',
                    color: mode === m ? '#fff' : 'var(--text3)',
                    transition: 'all 0.12s',
                  }}>
                  {m === 'full' ? '完整' : '快速'}
                </button>
              ))}
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
            <MessageSquarePlus size={13} /> 新建对话
          </button>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Clock size={13} style={{ color: 'var(--text3)' }} />
              <span className="t-caption">历史对话</span>
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
            <span className="animate-pulse">●</span> 正在生成 · 点击返回
          </div>
        )}

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {logs.length === 0 && (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>暂无历史记录</div>
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
                    {log.turn_count > 1 && <span className="badge" style={{ background: 'rgba(16,185,129,0.12)', color: '#10b981' }}>{log.turn_count} 轮</span>}
                    {log.id === currentLogId && streaming && (
                      <span className="animate-pulse" style={{ color: 'var(--accent)', fontSize: 10, lineHeight: 1 }}>●</span>
                    )}
                    <span style={{ fontSize: 10, color: 'var(--text3)' }}>{fmtTime(log.updated_at || log.created_at)}</span>
                  </div>
                  {log.seeds.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {log.seeds.slice(0, 4).map((s, i) => {
                        const color = DOMAIN_COLORS[s.domain] || '#6366f1'
                        return <span key={i} className="chip" style={{ background: color + '22', color, fontSize: 10 }}>{s.label}</span>
                      })}
                    </div>
                  )}
                </div>
                <button
                  className="log-delete-btn"
                  onClick={async e => {
                    e.stopPropagation()
                    const ok = await confirm({ title: '删除记录', message: '此条查询记录将被永久删除。', confirmLabel: '删除', danger: true })
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

function ToolCallRow({ tc }: { tc: ToolCall }) {
  const [open, setOpen] = useState(false)
  const label = TOOL_LABELS[tc.tool] ?? tc.tool
  const hasDetail = tc.detail && (tc.detail.nodes.length > 0 || tc.detail.edges.length > 0)

  return (
    <div style={{
      borderRadius: 8, border: '1px solid var(--border2)',
      background: 'var(--surface2)', overflow: 'hidden', fontSize: 12,
    }}>
      <div
        onClick={() => hasDetail && setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px',
          cursor: hasDetail ? 'pointer' : 'default',
          userSelect: 'none',
        }}
      >
        <span style={{ color: 'var(--accent2)', fontWeight: 600, fontFamily: 'monospace' }}>{label}</span>
        <span style={{ color: 'var(--text3)' }}>R{tc.round}</span>
        {tc.summary ? (
          <span style={{ flex: 1, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{tc.summary}</span>
        ) : (
          <span style={{ flex: 1, color: 'var(--text3)', fontStyle: 'italic' }}>
            {Object.entries(tc.args).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(', ')}
          </span>
        )}
        {tc.node_count != null && tc.node_count > 0 && (
          <span className="badge" style={{ background: 'rgba(99,102,241,0.12)', color: 'var(--accent2)', flexShrink: 0 }}>{tc.node_count} 节点</span>
        )}
        {hasDetail && (
          <span style={{ color: 'var(--text3)', flexShrink: 0 }}>{open ? '▲' : '▼'}</span>
        )}
      </div>

      {open && hasDetail && tc.detail && (
        <div style={{ borderTop: '1px solid var(--border2)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {tc.detail.nodes.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>节点</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {tc.detail.nodes.map((n, i) => {
                  const color = DOMAIN_COLORS[n.domain] || '#6366f1'
                  return (
                    <div key={i} style={{ padding: '6px 8px', borderRadius: 6, background: 'var(--surface)', border: '1px solid var(--border)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text)', fontSize: 11 }}>{n.label}</span>
                        <span className="badge" style={{ background: color + '22', color, fontSize: 10 }}>{n.domain}</span>
                        <span style={{ color: n.origin === 'internal' ? 'var(--accent2)' : 'var(--text3)', fontSize: 10 }}>
                          {n.origin === 'internal' ? '内源' : '外源'}
                        </span>
                        <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 10 }}>
                          str {n.strength?.toFixed ? n.strength.toFixed(2) : n.strength}
                          {n.sim != null ? ` · sim ${n.sim.toFixed(3)}` : ''}
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
          {tc.detail.edges.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>边</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {tc.detail.edges.map((e, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text2)', fontSize: 11 }}>
                    <span style={{ color: 'var(--text)' }}>{e.from_label}</span>
                    <span style={{ color: 'var(--accent2)', fontWeight: 500 }}>—{e.relation_type}→</span>
                    <span style={{ color: 'var(--text)' }}>{e.to_label}</span>
                    <span style={{ color: 'var(--text3)', marginLeft: 'auto' }}>{e.weight?.toFixed ? e.weight.toFixed(3) : e.weight}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ThemeResultCard({ result }: { result: ThemeResult }) {
  const [showEntries, setShowEntries] = useState(false)
  const n = result.node
  const color = DOMAIN_COLORS[n.domain] || '#6366f1'

  return (
    <div style={{ borderRadius: 10, border: '1px solid var(--border)', overflow: 'hidden', fontSize: 12 }}>
      <div style={{ padding: '10px 14px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="badge" style={{ background: color + '22', color }}>{n.domain} · {n.node_type}</span>
          <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 13 }}>{n.label}</span>
          <span style={{ color: n.origin === 'internal' ? 'var(--accent2)' : 'var(--text3)', fontSize: 10 }}>
            {n.origin === 'internal' ? '内源' : '外源'}
          </span>
          <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 10, flexShrink: 0 }}>
            strength {n.strength.toFixed(3)}
          </span>
        </div>
        {n.description && (
          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text3)', lineHeight: 1.5 }}>{n.description}</div>
        )}
      </div>

      {result.entries.length > 0 && (
        <>
          <button
            onClick={() => setShowEntries(v => !v)}
            style={{
              width: '100%', padding: '6px 14px', background: 'none',
              border: 'none', borderBottom: showEntries ? '1px solid var(--border)' : 'none',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
              color: 'var(--text3)', fontSize: 11, textAlign: 'left',
            }}
          >
            <span style={{ color: 'var(--accent2)' }}>{showEntries ? '▲' : '▼'}</span>
            {result.entries.length} 条原始记录（点击展开）
          </button>
          {showEntries && (
            <div style={{
              padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 10,
              borderBottom: '1px solid var(--border)', background: 'var(--surface)',
            }}>
              {result.entries.map((e, i) => (
                <div key={i}>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 3 }}>{e.date}</div>
                  <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.65, fontStyle: 'italic' }}>
                    「{e.raw}」
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <div style={{ padding: '12px 14px', color: 'var(--text)', lineHeight: 1.75, fontSize: 12 }}>
        {result.analysis}
      </div>
    </div>
  )
}

function HistoryContextBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ marginBottom: 12, borderRadius: 8, border: '1px solid var(--border2)', overflow: 'hidden', fontSize: 12 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{ width: '100%', padding: '6px 12px', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text3)', fontSize: 11, textAlign: 'left' }}
      >
        <span style={{ color: 'var(--accent2)' }}>{open ? '▲' : '▼'}</span>
        注入的历史上下文
      </button>
      {open && (
        <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border2)', background: 'var(--surface)', color: 'var(--text2)', whiteSpace: 'pre-wrap', lineHeight: 1.65, fontSize: 11 }}>
          {text}
        </div>
      )}
    </div>
  )
}

function LogDetailView({ log }: { log: QueryLogDetail }) {
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
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>通用解答</div>
                  <MarkdownText text={turn.q1_text} />
                </div>
              )}
              {turn.q2_text && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>人格穿刺</div>
                  <MarkdownText text={turn.q2_text} />
                </div>
              )}
              {turn.response && (
                <div>
                  {(turn.q1_text || turn.q2_text) && (
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent2)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>图谱洞察</div>
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
