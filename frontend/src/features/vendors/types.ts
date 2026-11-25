export interface Vendor {
  vendor_id: string
  name: string
  email: string | null
  /** Rung after we email them, with country code (+91...). */
  phone: string | null
  /** Language of that call: Hindi, Marathi or English. */
  call_language: CallLanguage
  reliability_score: number
  created_at: string
  /** Set when the mail server said emails to this address do not arrive; cleared when the address is changed. */
  email_bounced_at?: string | null
  email_bounce_reason?: string | null
}

export type CallLanguage = 'hi' | 'mr' | 'en'

export interface UpsertVendorRequest {
  name: string
  reliability_score: number
  /** Where quote requests, purchase orders and delivery chasers are emailed. */
  email?: string
  phone?: string
  call_language?: CallLanguage
}

/** Every detail of one supplier as it should be after the change (null clears an e-mail or phone). */
export interface UpdateVendorRequest {
  name: string
  reliability_score: number
  email: string | null
  phone: string | null
  call_language: CallLanguage
}

export interface Rfq {
  rfq_id: string
  case_id: string
  vendor_id: string
  vendor_name: string
  /** sent | replied */
  status: string
  sent_at: string
  last_contacted_at: string
  reminder_count: number
  deadline_at: string
  replied_at: string | null
}

export interface Quote {
  quote_id: string
  case_id: string
  vendor_id: string
  vendor_name: string
  raw_quote_text: string
  price: number | null
  lead_time_days: number | null
  terms: string | null
  created_at: string
}

export interface SubmitQuoteRequest {
  vendor_id: string
  raw_quote_text: string
}

export interface VendorSelection {
  case_id: string
  vendor_id: string
  vendor_name: string
  rationale: string | null
  created_at: string
}
