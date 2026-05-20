// API client for /ui/api/contacts/*
const BASE = '/ui/api/contacts'

export type ContactKind =
  | 'friend' | 'colleague' | 'family' | 'romantic'
  | 'mentor' | 'client' | 'acquaintance'

export type ContactStatus = 'candidate' | 'confirmed' | 'merged'
export type ActiveStatus  = 'active' | 'dormant' | 'severed'

export interface Contact {
  id: number
  display_name: string
  aliases: string[]
  status: ContactStatus
  merged_into_id: number | null
  relationship_kind: ContactKind | null
  kind_locked: boolean
  field_locks: Record<string, boolean>
  active_status: ActiveStatus | null
  intimacy_score: number | null
  first_seen_entry_id: number | null
  last_seen_entry_id: number | null
  last_interaction_at: string | null
  context_summary: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Evidence {
  id: number
  contact_id: number | null
  entry_id: number
  mention_text: string
  excerpt: string
  confidence: number
  suggested_kind: ContactKind | null
  ambiguous_candidate_ids: number[]
  interaction_observed: boolean
  created_at: string
  entry_excerpt?: string
}

async function jfetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) {
    const text = await r.text().catch(() => '')
    throw new Error(`${r.status} ${text}`)
  }
  return r.json() as Promise<T>
}

export const ContactsAPI = {
  list: (params: { status?: string; kind?: ContactKind; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.status) q.set('status', params.status)
    if (params.kind)   q.set('kind', params.kind)
    if (params.limit !== undefined)  q.set('limit', String(params.limit))
    if (params.offset !== undefined) q.set('offset', String(params.offset))
    const qs = q.toString()
    return jfetch<{ items: Contact[]; total: number }>(`${qs ? '?' + qs : ''}`)
  },

  ambiguous: () => jfetch<{ items: Evidence[] }>('/ambiguous'),

  detail: (id: number) => jfetch<{ contact: Contact & { merged_into?: Contact | null }; evidence: Evidence[] }>(`/${id}`),

  create: (body: Partial<Contact> & { display_name: string }) =>
    jfetch<Contact>('', { method: 'POST', body: JSON.stringify(body) }),

  confirm: (id: number, body: Partial<Contact>) =>
    jfetch<Contact>(`/${id}/confirm`, { method: 'POST', body: JSON.stringify(body) }),

  patch: (id: number, body: Partial<Contact> & { kind_locked?: boolean }) =>
    jfetch<Contact>(`/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  merge: (id: number, into_id: number) =>
    jfetch<{ merged_id: number; into_id: number; evidence_moved: number }>(
      `/${id}/merge`, { method: 'POST', body: JSON.stringify({ into_id }) }
    ),

  assignEvidence: (ev_id: number, body: { contact_id?: number; create_new?: boolean;
                                          display_name?: string; aliases?: string[];
                                          relationship_kind?: ContactKind; context_summary?: string }) =>
    jfetch<{ evidence_id: number; contact_id: number }>(
      `/evidence/${ev_id}/assign`, { method: 'POST', body: JSON.stringify(body) }
    ),

  dismissEvidence: (ev_id: number) =>
    jfetch<{ ok: boolean }>(`/evidence/${ev_id}/dismiss`, { method: 'POST' }),

  remove: (id: number) =>
    jfetch<{ deleted_id: number }>(`/${id}`, { method: 'DELETE' }),
}
