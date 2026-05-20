import { useState } from 'react'
import { ContactsAPI, type Contact, type Evidence } from '../../api/contacts'
import { useI18n } from '../../i18n'
import { MergeDialog } from './MergeDialog'

interface Props {
  candidates: Contact[]
  ambiguous: Evidence[]
  confirmed: Contact[]
  onChanged: () => void
  onSelect: (id: number) => void
}

export function PendingQueue({ candidates, ambiguous, confirmed, onChanged, onSelect }: Props) {
  const { t } = useI18n()
  const [mergeFor, setMergeFor] = useState<Contact | null>(null)

  return (
    <div className="flex flex-col h-full border rounded p-2 overflow-y-auto">
      <div className="font-medium mb-2">{t('contacts.candidates_count', { count: candidates.length })}</div>
      {candidates.length === 0
        ? <div className="text-sm opacity-60 mb-4">{t('contacts.candidate_empty')}</div>
        : candidates.map(c => (
            <div key={c.id} className="border rounded p-2 mb-2">
              <div className="font-medium">{c.display_name}</div>
              <div className="text-xs opacity-70 mb-1">
                {c.relationship_kind ? t(`contacts.kind_${c.relationship_kind}` as any) : t('contacts.kind_unknown')} · {c.context_summary}
              </div>
              <div className="flex gap-2">
                <button className="border px-2 py-0.5 text-xs"
                        onClick={async () => { await ContactsAPI.confirm(c.id, {}); onChanged(); onSelect(c.id) }}>
                  {t('contacts.action_confirm')}
                </button>
                <button className="border px-2 py-0.5 text-xs" onClick={() => setMergeFor(c)}>
                  {t('contacts.action_merge')}
                </button>
                <button className="border px-2 py-0.5 text-xs"
                        onClick={async () => {
                          if (!confirm(`${t('contacts.action_delete')}?`)) return
                          await ContactsAPI.remove(c.id); onChanged()
                        }}>
                  {t('contacts.action_delete')}
                </button>
              </div>
            </div>
          ))
      }

      <div className="font-medium my-2">{t('contacts.ambiguous_count', { count: ambiguous.length })}</div>
      {ambiguous.length === 0
        ? <div className="text-sm opacity-60">{t('contacts.ambiguous_empty')}</div>
        : ambiguous.map(ev => (
            <AmbiguousCard key={ev.id} ev={ev} confirmed={confirmed} onChanged={onChanged} />
          ))
      }

      {mergeFor && (
        <MergeDialog source={mergeFor}
                     targets={[...confirmed, ...candidates.filter(c => c.id !== mergeFor.id)]}
                     onClose={() => setMergeFor(null)}
                     onDone={() => { setMergeFor(null); onChanged() }} />
      )}
    </div>
  )
}

function AmbiguousCard({ ev, confirmed, onChanged }: { ev: Evidence; confirmed: Contact[]; onChanged: () => void }) {
  const { t } = useI18n()
  const [picked, setPicked] = useState<number | 'new' | ''>('')
  const candidates = confirmed.filter(c => ev.ambiguous_candidate_ids.includes(c.id))

  return (
    <div className="border rounded p-2 mb-2">
      <div className="text-xs opacity-60 mb-1">{ev.entry_excerpt}</div>
      <div className="text-sm mb-1">"{ev.mention_text}"</div>
      <div className="text-xs">
        {candidates.map(c => (
          <label key={c.id} className="block">
            <input type="radio" name={`amb-${ev.id}`} value={c.id}
                   checked={picked === c.id}
                   onChange={() => setPicked(c.id)} /> {c.display_name}
          </label>
        ))}
        <label className="block">
          <input type="radio" name={`amb-${ev.id}`} value="new"
                 checked={picked === 'new'}
                 onChange={() => setPicked('new')} /> {t('contacts.action_new')}
        </label>
      </div>
      <div className="flex gap-2 mt-1">
        <button className="border px-2 py-0.5 text-xs" disabled={picked === ''}
                onClick={async () => {
                  if (picked === 'new') {
                    const name = prompt(t('contacts.field_display_name'))
                    if (!name) return
                    await ContactsAPI.assignEvidence(ev.id, { create_new: true, display_name: name })
                  } else if (typeof picked === 'number') {
                    await ContactsAPI.assignEvidence(ev.id, { contact_id: picked })
                  }
                  onChanged()
                }}>
          OK
        </button>
        <button className="border px-2 py-0.5 text-xs"
                onClick={async () => { await ContactsAPI.dismissEvidence(ev.id); onChanged() }}>
          {t('contacts.action_dismiss')}
        </button>
      </div>
    </div>
  )
}
