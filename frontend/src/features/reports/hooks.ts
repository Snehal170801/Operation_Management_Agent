import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api-client'
import type { Report } from './types'

/** The management report for the last `days` days (0 = everything so far). Under 'reports', and re-read every
 *  minute while open: it is a summary, so it does not need the live connection. */
export const useReport = (days: number) =>
  useQuery({
    queryKey: ['reports', days],
    queryFn: () => api.get<Report>(`/reports?days=${days}`),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  })
