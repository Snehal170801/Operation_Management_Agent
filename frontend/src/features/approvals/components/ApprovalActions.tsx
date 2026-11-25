import { useState } from 'react'
import { Check, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { NoteModal } from '@/components/ui/NoteModal'
import { useApprovalReview, useDecideApproval } from '../hooks'
import { RejectModal } from './RejectModal'

/** Approve / Reject for one pending approval. The server records who decided from the session. */
export function ApprovalActions({ approvalId, kind = 'vendor_selection' }: { approvalId: string; kind?: string }) {
  const [mode, setMode] = useState<'approve' | 'reject' | null>(null)
  const decide = useDecideApproval()
  // Only needed once someone starts to reject: it says whether asking the suppliers again is still allowed.
  const review = useApprovalReview(approvalId, mode === 'reject')

  function close() {
    setMode(null)
    decide.reset()
  }

  return (
    <>
      <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
        <Button className="h-11 px-4 sm:h-9 sm:px-3" onClick={() => setMode('approve')}>
          <Check size={16} /> Approve
        </Button>
        <Button variant="secondary" className="h-11 px-4 sm:h-9 sm:px-3" onClick={() => setMode('reject')}>
          <X size={16} /> Reject
        </Button>
      </div>

      {kind === 'price_change' ? (
        <>
          <NoteModal
            open={mode === 'approve'}
            title="Accept the higher price?"
            description="The order total becomes the new price and the supplier is told you accept."
            confirmLabel="Accept the new price"
            loading={decide.isPending}
            error={decide.error}
            onClose={close}
            onConfirm={(note) => decide.mutate({ approvalId, approve: true, note }, { onSuccess: close })}
          />
          <NoteModal
            open={mode === 'reject'}
            title="Refuse the higher price?"
            description="The supplier is asked to honour the agreed price. The order stays open and the purchasing team follows up."
            confirmLabel="Refuse"
            danger
            loading={decide.isPending}
            error={decide.error}
            onClose={close}
            onConfirm={(note) => decide.mutate({ approvalId, approve: false, note }, { onSuccess: close })}
          />
        </>
      ) : (
        <>
      <NoteModal
        open={mode === 'approve'}
        title="Approve this vendor selection?"
        description="The purchase order will be created and emailed to the vendor automatically."
        confirmLabel="Approve"
        loading={decide.isPending}
        error={decide.error}
        onClose={close}
        onConfirm={(note) => decide.mutate({ approvalId, approve: true, note }, { onSuccess: close })}
      />
      <RejectModal
        open={mode === 'reject' && !review.isLoading}
        canAskAgain={!!review.data?.can_ask_again}
        selectedSupplier={review.data?.options.find((o) => o.vendor_id === review.data?.selected_vendor_id)?.vendor_name}
        loading={decide.isPending}
        error={decide.error}
        onClose={close}
        onConfirm={({ note, reSource, skipSelected }) =>
          decide.mutate({ approvalId, approve: false, note, reSource, skipSelected }, { onSuccess: close })
        }
      />
        </>
      )}
    </>
  )
}
