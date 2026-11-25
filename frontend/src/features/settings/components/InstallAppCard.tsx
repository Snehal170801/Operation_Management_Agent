import { useEffect, useState } from 'react'
import { Download, Smartphone } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'

interface InstallEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent)

/** Put the app on the phone's home screen. Chrome and Edge offer a button; iPhones have no such button, so they get the two taps to make. */
export function InstallAppCard() {
  const [event, setEvent] = useState<InstallEvent | null>(null)
  const [installed, setInstalled] = useState(() => isStandalone())

  useEffect(() => {
    const before = (e: Event) => { e.preventDefault(); setEvent(e as InstallEvent) }
    const done = () => { setInstalled(true); setEvent(null) }
    window.addEventListener('beforeinstallprompt', before)
    window.addEventListener('appinstalled', done)
    return () => { window.removeEventListener('beforeinstallprompt', before); window.removeEventListener('appinstalled', done) }
  }, [])

  return (
    <Card title="Use it like an app">
      <div className="flex items-start gap-3 text-sm">
        <Smartphone size={20} className="mt-0.5 shrink-0 text-brand-ink" />
        {installed ? (
          <p className="text-title">This device already has Operation Agents installed. Open it from the home screen or the app list.</p>
        ) : event ? (
          <div className="flex flex-col items-start gap-3">
            <p className="text-title">Install Operation Agents on this device to open it from the home screen, full screen, like any other app.</p>
            <Button onClick={() => { void event.prompt().then(() => event.userChoice).then(() => setEvent(null)) }}>
              <Download size={16} /> Install the app
            </Button>
          </div>
        ) : isIos() ? (
          <p className="text-title">On an iPhone or iPad: tap the <b>Share</b> button in Safari, then <b>Add to Home Screen</b>.</p>
        ) : (
          <p className="text-muted">Your browser will offer to install this app when it can (look for an install icon in the address bar or "Install app" in the browser menu).</p>
        )}
      </div>
    </Card>
  )
}
