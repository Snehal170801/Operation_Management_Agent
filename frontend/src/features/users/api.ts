import { api } from '@/lib/api-client'
import type { CreateUserRequest, Department, ManagedUser, PermissionGroup, UpdateUserRequest } from './types'

export const usersApi = {
  list: () => api.get<ManagedUser[]>('/users'),
  permissions: () => api.get<PermissionGroup[]>('/users/permissions'),
  departments: () => api.get<Department[]>('/users/departments'),
  create: (body: CreateUserRequest) => api.post<ManagedUser>('/users', body),
  update: (userId: string, body: UpdateUserRequest) => api.patch<ManagedUser>(`/users/${userId}`, body),
  resetPassword: (userId: string, newPassword: string) =>
    api.post<void>(`/users/${userId}/reset-password`, { new_password: newPassword }),
  remove: (userId: string) => api.delete<void>(`/users/${userId}`),
  unlock: (userId: string) => api.post<ManagedUser>(`/users/${userId}/unlock`),
}
