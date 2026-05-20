import { useEffect, useState } from 'react'
import { ContactsAPI, type Contact, type Evidence } from '../../api/contacts'
import { useI18n } from '../../i18n'
import { ContactEditForm } from './ContactEditForm'

interface Props {
  contactId: number | null
  confirmed: Contact[]
  onChanged: () => void
}

export function ContactDetail({ contactId, confirmed, onChanged }: Props) {
  const { t } = useI18n()
  const [contact, setContact] = useState<Contact | null>(null)
  const [evidence, setEvidence] = useState<Evidence[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (contactId == null) { setContact(null); setEvidence([]); return }
    setLoading(true)
    ContactsAPI.detail(contactId)
      .then(d => { setContact(d.contact); setEvidence(d.evidence) })
      .finally(() => setLoading(false))
  }, [contactId])

  if (contactId == null) return <div className="border rounded p-2 text-sm opacity-60">←</div>
  if (loading || !contact) return <div className="border rounded p-2">…</div>

  return (
    <div className="border rounded p-2 overflow-y-auto h-full flex flex-col gap-2">
      <ContactEditForm contact={contact} onSaved={() => { onChanged(); ContactsAPI.detail(contact.id).then(d => { setContact(d.contact); setEvidence(d.evidence) }) }} />
      <hr className="my-2" />
      <div className="font-medium">{t('contacts.evidence_section_title', { count: evidence.length })}</div>
      {evidence.length === 0
        ? <div className="text-xs opacity-60">{t('contacts.evidence_empty')}</div>
        : evidence.map(ev => (
            <div key={ev.id} className="text-xs border rounded p-1">
              <div className="opacity-60">{ev.created_at}</div>
              <div>"{ev.excerpt || ev.mention_text}"</div>
            </div>
          ))
      }
    </div>
  )
}
