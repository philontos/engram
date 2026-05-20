import { useState } from 'react'
import { ContactsAPI, type Contact } from '../../api/contacts'
import { useI18n } from '../../i18n'

interface Props {
  source: Contact
  targets: Contact[]
  onClose: () => void
  onDone: () => void
}

export function MergeDialog({ source, targets, onClose, onDone }: Props) {
  const { t } = useI18n()
  const [pickId, setPickId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const target = targets.find(tgt => tgt.id === pickId) || null

  const submit = async () => {
    if (pickId == null) return
    setBusy(true)
    try { await ContactsAPI.merge(source.id, pickId); onDone() }
    catch (err) { alert(t('contacts.alert_merge_failed', { error: String(err) })) }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded p-4 w-[480px] max-h-[80vh] overflow-y-auto">
        <div className="font-medium mb-2">{t('contacts.merge_dialog_title')}</div>
        <div className="text-xs opacity-60 mb-2">{source.display_name}</div>
        <select className="border px-2 py-1 w-full mb-2"
                value={pickId ?? ''}
                onChange={e => setPickId(e.target.value ? Number(e.target.value) : null)}>
          <option value="">--</option>
          {targets.map(c => <option key={c.id} value={c.id}>{c.display_name} ({c.status})</option>)}
        </select>
        {target && (
          <div className="text-xs border rounded p-2 mb-2">
            <div className="font-medium">{t('contacts.merge_dialog_preview')}</div>
            <div>aliases → {JSON.stringify(Array.from(new Set([...target.aliases, ...source.aliases, source.display_name])))}</div>
            <div>kind → {target.relationship_kind ?? source.relationship_kind ?? '(null)'}</div>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button className="border px-3 py-1" onClick={onClose}>{t('common.cancel')}</button>
          <button className="border px-3 py-1" onClick={submit} disabled={pickId == null || busy}>
            {t('contacts.merge_dialog_confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}
