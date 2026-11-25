import fs from 'node:fs'
import path from 'node:path'

// The folder the test API writes its "sent" email to and reads supplier replies from (see docs/TESTING_SWITCHES.md).
export const MAIL_DIR = process.env.E2E_MAIL_DIR ?? path.resolve(import.meta.dirname, '..', '.runtime', 'mail')
const OUTBOX = path.join(MAIL_DIR, 'outbox')
const INBOX = path.join(MAIL_DIR, 'inbox')

export interface Mail { to: string; subject: string; body: string; html?: string; sent_at: string; file: string }

export function clearMail() {
  for (const dir of [OUTBOX, INBOX]) {
    fs.mkdirSync(dir, { recursive: true })
    for (const f of fs.readdirSync(dir)) fs.rmSync(path.join(dir, f), { recursive: true, force: true })
  }
}

export function readOutbox(filter: { to?: string; subject?: string | RegExp } = {}): Mail[] {
  if (!fs.existsSync(OUTBOX)) return []
  return fs.readdirSync(OUTBOX).filter((f) => f.endsWith('.json')).flatMap((f) => {
    try { return [{ ...JSON.parse(fs.readFileSync(path.join(OUTBOX, f), 'utf8')), file: f } as Mail] } catch { return [] } // half-written
  }).filter((m) => (!filter.to || m.to.toLowerCase().includes(filter.to.toLowerCase()))
    && (!filter.subject || (typeof filter.subject === 'string' ? m.subject.includes(filter.subject) : filter.subject.test(m.subject))))
    .sort((a, b) => a.sent_at.localeCompare(b.sent_at) || a.file.localeCompare(b.file))
}

/** Waits until at least `count` matching emails exist, and returns them. */
export async function waitForMail(filter: Parameters<typeof readOutbox>[0], count = 1, timeoutMs = 60_000): Promise<Mail[]> {
  const end = Date.now() + timeoutMs
  for (;;) {
    const found = readOutbox(filter)
    if (found.length >= count) return found
    if (Date.now() > end) throw new Error(`Timed out waiting for ${count} email(s) matching ${JSON.stringify(filter)}; outbox has: ${readOutbox().map((m) => `[${m.to}] ${m.subject}`).join(' | ') || 'nothing'}`)
    await new Promise((r) => setTimeout(r, 500))
  }
}

let counter = 0
/** Plays a supplier: writes a message into the inbox (under a temporary name, then renames, so the app never reads half a file). */
export function dropInbound(fromEmail: string, subject: string, body: string, attachments?: { name: string; text: string }[]) {
  fs.mkdirSync(INBOX, { recursive: true })
  const name = `${Date.now()}-${process.pid}-${counter++}.json`
  const tmp = path.join(INBOX, name + '.tmp')
  fs.writeFileSync(tmp, JSON.stringify({ from_email: fromEmail, subject, body, ...(attachments ? { attachments } : {}) }))
  fs.renameSync(tmp, path.join(INBOX, name))
}

/** A supplier's reply to an email the app sent: same subject (so the case tag stays), "Re: " in front. */
export function replyTo(sent: Mail, fromEmail: string, body: string) {
  dropInbound(fromEmail, /^re:/i.test(sent.subject) ? sent.subject : `Re: ${sent.subject}`, body)
}

/** The /decide/<token> link of an approval email (a = approve | refuse). */
export function decisionLink(mail: Mail, action: 'approve' | 'refuse' = 'approve'): string {
  const text = `${mail.body}\n${mail.html ?? ''}`
  const m = text.match(/https?:\/\/[^\s"'<>]+\/decide\/[A-Za-z0-9_\-]+(?:\?[^\s"'<>]*)?/g) ?? []
  const hit = m.map((u) => u.replace(/&amp;/g, '&')).find((u) => u.includes(`a=${action}`)) ?? m[0]
  if (!hit) throw new Error(`No /decide link in the email "${mail.subject}"`)
  return hit
}
