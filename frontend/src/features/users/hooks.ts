import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { usersApi } from './api'
import type { UpdateUserRequest } from './types'

const KEY = ['users'] as const

export const useUsers = (enabled = true) => useQuery({ queryKey: KEY, queryFn: usersApi.list, enabled })
/** The modules and checkmarks offered on the access form. Fixed by the server, so cache it for good. */
export const usePermissionCatalog = () =>
  useQuery({ queryKey: ['users', 'permissions'], queryFn: usersApi.permissions, staleTime: Infinity })

/** The departments (one per agent) and the permissions each one needs. Fixed by the server. */
export const useDepartments = (enabled = true) => useQuery({ queryKey: ['users', 'departments'], queryFn: usersApi.departments, staleTime: Infinity, enabled })

function useInvalidating<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }) })
}

export const useCreateUser = () => useInvalidating(usersApi.create)
export const useUpdateUser = () =>
  useInvalidating(({ userId, body }: { userId: string; body: UpdateUserRequest }) => usersApi.update(userId, body))
export const useResetPassword = () =>
  useInvalidating(({ userId, password }: { userId: string; password: string }) =>
    usersApi.resetPassword(userId, password),
  )
export const useDeleteUser = () => useInvalidating(usersApi.remove)
export const useUnlockUser = () => useInvalidating(usersApi.unlock)
