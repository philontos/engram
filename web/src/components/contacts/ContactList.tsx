import { useState } from 'react'
import { ContactsAPI, type Contact, type ContactKind } from '../../api/contacts'
import { useI18n } from '../../i18n'

const KIND_KEYS: ContactKind[] = ['friend','colleague','family','romantic','mentor','client','acquaintance']

interface Props {
  title: string
  items: Contact[]
  selectedId: number | null
  onSelect: (id: number | null) => void
  onCreated: () => void
}

export function ContactList({ title, items, selectedId, onSelect, onCreated }: Props) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const [kindFilter, setKindFilter] = useState<ContactKind | ''>('')
  const [creating, setCreating] = useState(false)

  const filtered = items.filter(c => {
    if (kindFilter && c.relationship_kind !== kindFilter) return false
    if (!q) return true
    const hay = (c.display_name + ' ' + c.aliases.join(' ')).toLowerCase()
    return hay.includes(q.toLowerCase())
  })

  return (
    <div className="flex flex-col h-full border rounded p-2">
      <div className="font-medium mb-2">{title}</div>
      <div className="flex gap-2 mb-2">
        <input className="border px-2 py-1 flex-1"
               placeholder={t('contacts.search_placeholder')}
               value={q} onChange={e => setQ(e.target.value)} />
        <select className="border px-2 py-1"
                value={kindFilter} onChange={e => setKindFilter(e.target.value as ContactKind | '')}>
          <option value="">{t('contacts.filter_kind_all')}</option>
          {KIND_KEYS.map(k => <option key={k} value={k}>{t(`contacts.kind_${k}` as any)}</option>)}
        </select>
      </div>
      <div className="overflow-y-auto flex-1">
        {filtered.length === 0 && <div className="text-sm opacity-60">{t('contacts.confirm_empty')}</div>}
        {filtered.map(c => (
          <button key={c.id}
                  onClick={() => onSelect(c.id)}
                  className={`block w-full text-left p-2 hover:bg-gray-100 ${selectedId === c.id ? 'bg-gray-200' : ''}`}>
            <div>{c.display_name}</div>
            <div className="text-xs opacity-60">
              {c.relationship_kind ? t(`contacts.kind_${c.relationship_kind}` as any) : t('contacts.kind_unknown')}
            </div>
          </button>
        ))}
      </div>
      <button className="mt-2 border px-2 py-1"
              onClick={async () => {
                const name = prompt(t('contacts.field_display_name'))
                if (!name) return
                setCreating(true)
                try { await ContactsAPI.create({ display_name: name }); onCreated() } finally { setCreating(false) }
              }}
              disabled={creating}>
        + {t('contacts.action_new')}
      </button>
    </div>
  )
}
