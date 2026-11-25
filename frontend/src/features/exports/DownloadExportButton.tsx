import { useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { api } from '@/lib/api-client'

export type ExportKind = 'cases' | 'purchase-orders' | 'invoices' | 'stock'

/** Downloads a CSV or an Excel workbook from the server with the person's sign-in (a plain link would not carry it). The server decides what is included and
 * refuses anyone who may not have it; the reason is shown here instead of a silent failure. */
export function DownloadExportButton({ kind, label, format = 'csv' }: { kind: ExportKind; label: string; format?: 'csv' | 'xlsx' }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const blob = await api.blob(`/exports/${kind}.${format}`)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${kind}-${new Date().toISOString().slice(0, 10)}.${format}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The file could not be made.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button variant="secondary" onClick={download} loading={busy} disabled={busy}>
        <Download size={15} /> {label}
      </Button>
      {error && <span className="text-xs text-danger" role="alert">{error}</span>}
    </span>
  )
}
