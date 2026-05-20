import { useEffect, useState } from 'react'
import { ContactsAPI, type Contact, type ContactKind, type ActiveStatus } from '../../api/contacts'
import { useI18n } from '../../i18n'

const KINDS: ContactKind[] = ['friend','colleague','family','romantic','mentor','client','acquaintance']
const ACTIVES: ActiveStatus[] = ['active','dormant','severed']

interface Props { contact: Contact; onSaved: () => void }

export function ContactEditForm({ contact, onSaved }: Props) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Contact>(contact)
  useEffect(() => setDraft(contact), [contact])

  const setField = <K extends keyof Contact>(k: K, v: Contact[K]) => setDraft(d => ({ ...d, [k]: v }))

  const save = async () => {
    const body: Partial<Contact> & { kind_locked?: boolean } = {
      display_name: draft.display_name,
      aliases: draft.aliases,
      context_summary: draft.context_summary,
      active_status: draft.active_status,
      intimacy_score: draft.intimacy_score,
    }
    if (draft.relationship_kind !== contact.relationship_kind) {
      body.relationship_kind = draft.relationship_kind
    }
    try { await ContactsAPI.patch(contact.id, body); onSaved() }
    catch (err) { alert(t('contacts.alert_save_failed', { error: String(err) })) }
  }

  const resetKind = async () => {
    try {
      await ContactsAPI.patch(contact.id, { relationship_kind: null, kind_locked: false })
      onSaved()
    } catch (err) { alert(t('contacts.alert_save_failed', { error: String(err) })) }
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs">
        {t('contacts.field_display_name')}
        <input className="block w-full border px-2 py-1"
               value={draft.display_name}
               onChange={e => setField('display_name', e.target.value)} />
      </label>
      <label className="text-xs">
        {t('contacts.field_aliases')}
        <input className="block w-full border px-2 py-1"
               value={draft.aliases.join(', ')}
               onChange={e => setField('aliases', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} />
      </label>
      <label className="text-xs">
        {t('contacts.field_kind')}
        <span className="flex gap-2 items-center">
          <select className="border px-2 py-1 flex-1"
                  value={draft.relationship_kind ?? ''}
                  onChange={e => setField('relationship_kind', (e.target.value || null) as ContactKind | null)}>
            <option value="">{t('contacts.kind_unknown')}</option>
            {KINDS.map(k => <option key={k} value={k}>{t(`contacts.kind_${k}` as any)}</option>)}
          </select>
          {contact.kind_locked && (
            <>
              <span title={t('contacts.kind_locked_tooltip')}>🔒</span>
              <button type="button" className="border px-2 py-0.5 text-xs" onClick={resetKind}>
                {t('contacts.action_reset_kind')}
              </button>
            </>
          )}
        </span>
      </label>
      <label className="text-xs">
        {t('contacts.field_active_status')}
        <select className="block w-full border px-2 py-1"
                value={draft.active_status ?? ''}
                onChange={e => setField('active_status', (e.target.value || null) as ActiveStatus | null)}>
          <option value="">--</option>
          {ACTIVES.map(a => <option key={a} value={a}>{t(`contacts.active_${a}` as any)}</option>)}
        </select>
      </label>
      <label className="text-xs">
        {t('contacts.field_intimacy')}
        <input type="number" min="0" max="1" step="0.05" className="block w-full border px-2 py-1"
               value={draft.intimacy_score ?? ''}
               onChange={e => setField('intimacy_score', e.target.value === '' ? null : Number(e.target.value))} />
      </label>
      <label className="text-xs">
        {t('contacts.field_context_summary')}
        <textarea className="block w-full border px-2 py-1"
                  value={draft.context_summary}
                  onChange={e => setField('context_summary', e.target.value)} />
      </label>
      <button className="border px-3 py-1" onClick={save}>{t('contacts.action_save')}</button>
    </div>
  )
}
