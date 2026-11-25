export interface UnmatchedDocument {
  document_id: string
  from_email: string
  vendor_name: string | null
  subject: string
  summary: string
  file_names: string[]
  status: string
  created_at: string
}
