import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api-client'
import type { DocumentKind, DocumentPage } from './types'

export const useDocumentSearch = (q: string, kind: DocumentKind | '', limit: number, offset: number) =>
  useQuery({
    queryKey: ['document-store', q, kind, limit, offset],
    queryFn: () => api.get<DocumentPage>(`/document-store?limit=${limit}&offset=${offset}${q ? `&q=${encodeURIComponent(q)}` : ''}${kind ? `&kind=${kind}` : ''}`),
    placeholderData: keepPreviousData,
  })

export const useCaseDocuments = (caseId: string, enabled = true) =>
  useQuery({ queryKey: ['document-store', 'case', caseId], queryFn: () => api.get<DocumentPage>(`/cases/${encodeURIComponent(caseId)}/document-store`), enabled })
