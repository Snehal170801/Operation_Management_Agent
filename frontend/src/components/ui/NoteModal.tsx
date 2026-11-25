import { useState, type FormEvent } from 'react'
import { Button } from './Button'
import { Textarea } from './Field'
import { Modal } from './Modal'

interface NoteModalProps {
  open: boolean
  title: string
  /** Short explanation shown above the note box. */
  description?: string
  confirmLabel: string
  /** Style the confirm button as a destructive action. */
  danger?: boolean
  loading?: boolean
  error?: Error | null
  onClose: () => void
  onConfirm: (note: string | undefined) => void
}

/** Confirm an action with an optional note (approve / reject / confirm receipt). */
export function NoteModal({ open, title, onClose, ...form }: NoteModalProps) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      {/* Modal renders nothing while closed, so this form (and its note) starts empty each time. */}
      <NoteForm onClose={onClose} {...form} />
    </Modal>
  )
}

function NoteForm({
  description,
  confirmLabel,
  danger,
  loading,
  error,
  onClose,
  onConfirm,
}: Omit<NoteModalProps, 'open' | 'title'>) {
  const [note, setNote] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    onConfirm(note.trim() || undefined)
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      {description && <p className="text-sm text-muted">{description}</p>}
      <Textarea label="Note (optional)" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="text-sm text-danger">{error.message}</p>}
      <div className="flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={loading} className={danger ? 'bg-none! bg-danger!' : undefined}>
          {confirmLabel}
        </Button>
      </div>
    </form>
  )
}
