import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { storeRoomApi } from './api'

export const useStoreRoomOverview = () =>
  useQuery({ queryKey: ['store-room', 'overview'], queryFn: storeRoomApi.overview, refetchInterval: 30_000 })

/** One page of one dataset. The previous page stays on screen while the next one loads. */
export const useDatasetPage = (key: string, search: string, page: number, pageSize: number, enabled = true) =>
  useQuery({
    queryKey: ['store-room', key, search, page, pageSize],
    queryFn: () => storeRoomApi.page(key, search, pageSize, (page - 1) * pageSize),
    enabled: enabled && !!key,
    placeholderData: keepPreviousData,
  })

/** `value`, but only after it has stopped changing for `ms` (so typing doesn't fire a request per key). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}
