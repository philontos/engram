// stub — replaced in Task 21
import type { Contact } from '../../api/contacts'

interface Props { source: Contact; targets: Contact[]; onClose: () => void; onDone: () => void }
export function MergeDialog({ source, targets, onClose, onDone }: Props) {
  return <div className="border rounded p-2 mt-2">MergeDialog stub</div>
}
