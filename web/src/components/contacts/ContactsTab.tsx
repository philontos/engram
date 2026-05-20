import { useEffect, useState, useCallback } from 'react'
import { ContactsAPI, type Contact, type Evidence } from '../../api/contacts'
import { useI18n } from '../../i18n'
import { ContactList } from './ContactList'
import { PendingQueue } from './PendingQueue'
import { ContactDetail } from './ContactDetail'

export function ContactsTab() {
  const { t } = useI18n()
  const [confirmed, setConfirmed] = useState<Contact[]>([])
  const [candidates, setCandidates] = useState<Contact[]>([])
  const [ambiguous, setAmbiguous] = useState<Evidence[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const refreshAll = useCallback(async () => {
    const [a, b, amb] = await Promise.all([
      ContactsAPI.list({ status: 'confirmed' }),
      ContactsAPI.list({ status: 'candidate' }),
      ContactsAPI.ambiguous(),
    ])
    setConfirmed(a.items); setCandidates(b.items); setAmbiguous(amb.items)
  }, [])

  useEffect(() => { void refreshAll() }, [refreshAll])

  return (
    <div className="h-full grid grid-cols-3 gap-4 p-4">
      <ContactList
        title={t('contacts.confirmed_count', { count: confirmed.length })}
        items={confirmed}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onCreated={refreshAll}
      />
      <PendingQueue
        candidates={candidates}
        ambiguous={ambiguous}
        confirmed={confirmed}
        onChanged={refreshAll}
        onSelect={setSelectedId}
      />
      <ContactDetail
        contactId={selectedId}
        confirmed={confirmed}
        onChanged={refreshAll}
      />
    </div>
  )
}
