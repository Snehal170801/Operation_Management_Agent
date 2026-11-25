import { useSyncExternalStore } from 'react'

/** Desktop (browser) notifications: a native pop-up for something that needs a person, shown when the app is open
 *  but not the tab you are looking at. The browser asks permission once; it can be turned off in its site settings. */

export type DesktopState = 'unsupported' | 'default' | 'granted' | 'denied'

const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

export function desktopState(): DesktopState {
  return typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
}

export function useDesktopState(): DesktopState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    desktopState,
  )
}

export async function enableDesktop(): Promise<DesktopState> {
  if (desktopState() === 'unsupported') return 'unsupported'
  try {
    await Notification.requestPermission()
  } catch {
    /* some browsers throw when asked from a blocked context: the state below says what happened */
  }
  emit()
  return desktopState()
}

/** Show one, only when the person is not looking at this tab (the in-app pop-up covers the rest). */
export function showDesktop(title: string, body: string, link: string, id: string): void {
  if (desktopState() !== 'granted' || !document.hidden) return
  try {
    const n = new Notification(title, { body, tag: id, icon: '/favicon.svg' })
    n.onclick = () => {
      window.focus()
      window.location.assign(link)
      n.close()
    }
  } catch {
    /* a browser that refuses (e.g. some phones need a service worker): the in-app alert still works */
  }
}
