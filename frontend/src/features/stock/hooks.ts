import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { stockApi } from './api'

const KEY = ['stock'] as const

export const useStock = () => useQuery({ queryKey: KEY, queryFn: stockApi.list, refetchInterval: 30_000 })

/** Every change to one item's count, newest first. Only fetched while the history is open. */
export const useStockHistory = (item: string | null) =>
  useQuery({ queryKey: ['stock-history', item], queryFn: () => stockApi.history(item as string), enabled: !!item })

export function useUpsertStock() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: stockApi.upsert,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['stock-history'] })
      return queryClient.invalidateQueries({ queryKey: KEY })
    },
  })
}

/** Rename an item or change its unit, category or preferred supplier. */
export function useUpdateStockItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: stockApi.updateItem,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['stock-history'] }) // the history follows a new name
      return queryClient.invalidateQueries({ queryKey: KEY })
    },
  })
}

/** Remove an item. The server refuses while an open order or request refers to it, and says which. */
export function useRemoveStockItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: stockApi.removeItem,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}

export function useSetLevels() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: stockApi.setLevels,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}

export function useReorder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: stockApi.reorder,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEY })
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })
}
