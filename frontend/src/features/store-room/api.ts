import { api } from '@/lib/api-client'
import { BASE_URL, toApiError } from '@/lib/http'
import { refreshSession, tokenStore } from '@/lib/session'
import type { DatasetPage, StoreRoomOverview } from './types'

export const storeRoomApi = {
  overview: () => api.get<StoreRoomOverview>('/store-room'),
  page: (key: string, search: string, limit: number, offset: number) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (search.trim()) params.set('search', search.trim())
    return api.get<DatasetPage>(`/store-room/${key}?${params}`)
  },
}

/** Downloads the dataset (filtered by `search`) as a CSV file. A file download can't go through the JSON
 *  client, so this signs the request itself and retries once if the session had just expired. */
export async function downloadCsv(key: string, search: string): Promise<void> {
  const url = `${BASE_URL}/store-room/${key}/export${search.trim() ? `?search=${encodeURIComponent(search.trim())}` : ''}`
  const send = () =>
    fetch(url, { credentials: 'include', headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } })

  let response = await send()
  if (response.status === 401 && (await refreshSession())) response = await send()
  if (!response.ok) throw await toApiError(response)

  const link = document.createElement('a')
  link.href = URL.createObjectURL(await response.blob())
  link.download = `${key}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(link.href)
}
