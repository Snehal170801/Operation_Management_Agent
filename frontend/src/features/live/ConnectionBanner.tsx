import { useEffect, useState } from 'react'
import { WifiOff } from 'lucide-react'
import { useLiveConnected } from './liveStore'

/** How long the live connection may be down before the person is told. The server renews it every few minutes,
 *  and a brief reconnect is normal, so a short gap must not flash a warning. */
const GRACE_MS = 15_000

/** A slim bar across the top when the app cannot reach the server: the pages stop updating by themselves, so
 *  say so instead of letting someone trust stale numbers. It goes away on its own the moment the link is back. */
export function ConnectionBanner() {
  const connected = useLiveConnected()
  const [lost, setLost] = useState(false)

  useEffect(() => {
    if (connected) {
      setLost(false)
      return
    }
    const timer = setTimeout(() => setLost(true), GRACE_MS)
    return () => clearTimeout(timer)
  }, [connected])

  if (!lost) return null
  return (
    <div role="alert" className="flex shrink-0 flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-red-600 px-4 py-2 text-sm text-white">
      <WifiOff size={16} aria-hidden />
      <span>
        <b>Can't reach the server.</b> What you see may be out of date. This page keeps retrying and will catch up by itself.
      </span>
    </div>
  )
}
