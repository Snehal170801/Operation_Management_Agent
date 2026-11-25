import { api } from '@/lib/api-client'
import type { AgentBoard, AgentInfo, AgentReplay, AgentFlowCase, AgentFlowState } from './types'

export const agentFlowApi = {
  /** The cases this person may look at: a requester's own, or everyone's for staff. Active ones first. */
  cases: () => api.get<AgentFlowCase[]>('/agent-flow/cases'),
  /** Staff only: every agent's workload across the open cases. */
  board: () => api.get<AgentBoard>('/agent-flow/board'),
  replay: (caseId: string) => api.get<AgentReplay>(`/agent-flow/cases/${caseId}/replay`),
  /** Everything one agent did on this case. */
  agentInfo: (caseId: string, key: string, at?: string) =>
    api.get<AgentInfo>(`/agent-flow/cases/${caseId}/agents/${key}${at ? `?at=${encodeURIComponent(at)}` : ''}`),
  flow: (caseId: string) => api.get<AgentFlowState>(`/agent-flow/cases/${caseId}`),
}
