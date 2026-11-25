import type { CallLanguage } from './types'

export const LANGUAGES: { value: CallLanguage; label: string }[] = [
  { value: 'hi', label: 'Hindi' },
  { value: 'mr', label: 'Marathi' },
  { value: 'en', label: 'English' },
]

/** "9325642310", "09325642310", "93256 42310" -> "+919325642310". Returns null if it isn't a phone number. */
export function toPhone(input: string): string | null {
  const raw = input.trim()
  if (!raw) return null
  const digits = raw.replace(/\D/g, '')
  if (raw.startsWith('+')) return digits.length >= 8 && digits.length <= 15 ? `+${digits}` : null
  if (digits.length === 10) return `+91${digits}`
  if (digits.length === 11 && digits.startsWith('0')) return `+91${digits.slice(1)}`
  if (digits.length === 12 && digits.startsWith('91')) return `+${digits}`
  return null
}
