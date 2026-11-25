import { useSyncExternalStore } from 'react'

const QUERY = '(max-width: 639px)'            // Tailwind's `sm` breakpoint: below it the layout is the phone layout

function subscribe(onChange: () => void) {
  const media = window.matchMedia(QUERY)
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}

/** True on a phone-width screen (and follows a rotation or resize). */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false)
}
