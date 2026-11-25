import { useQuery } from '@tanstack/react-query'
import { pollMs, useLiveConnected } from '@/features/live/liveStore'
import { agentFlowApi } from './api'

/** How often a case still being worked on is re-read. Short, because this page is for watching. */
export const FLOW_POLL_MS = 2_000
/** How often the list of cases is re-read, so a request submitted a moment ago shows up. */
export const CASES_POLL_MS = 5_000

/** Polling pauses while the tab is hidden (react-query default) and refreshes at once when you come back. */
export const useFlowCases = () => {
  const live = useLiveConnected()
  return useQuery({
    queryKey: ['agent-flow', 'cases'],
    queryFn: agentFlowApi.cases,
    refetchInterval: pollMs(live, CASES_POLL_MS),
    refetchOnWindowFocus: true,
  })
}

/** One case's agents. Re-read every couple of seconds while the case is open; once it is finished nothing
 *  can change any more, so polling stops (the final state stays on screen). */
export const useAgentFlow = (caseId: string | undefined) => {
  const live = useLiveConnected()
  return useQuery({
    queryKey: ['agent-flow', 'case', caseId],
    queryFn: () => agentFlowApi.flow(caseId as string),
    enabled: !!caseId,
    refetchInterval: (query) => (query.state.data?.status === 'closed' ? false : pollMs(live, FLOW_POLL_MS)),
    refetchOnWindowFocus: true,
  })
}

/** One agent's full detail, for the box that opens when you click it. Under 'agent-flow', so the live connection
 *  refreshes it the moment something changes; while a case is open it also re-reads on the slow safety-net timer. */
export const useAgentInfo = (caseId: string | undefined, key: string | undefined, closed: boolean) => {
  const live = useLiveConnected()
  return useQuery({
    queryKey: ['agent-flow', 'agent', caseId, key],
    queryFn: () => agentFlowApi.agentInfo(caseId as string, key as string),
    enabled: !!caseId && !!key,
    refetchInterval: closed ? false : pollMs(live, 3_000),
    refetchOnWindowFocus: true,
  })
}

/** One agent's full detail as it stood at a moment of a replay. The past never changes, so it is read once and kept. */
export const useAgentInfoAt = (caseId: string | undefined, key: string | undefined, at: string | undefined) =>
  useQuery({
    queryKey: ['agent-flow', 'agent-at', caseId, key, at],
    queryFn: () => agentFlowApi.agentInfo(caseId as string, key as string, at),
    enabled: !!caseId && !!key && !!at,
    staleTime: Infinity,
  })

/** The admin board: re-read every few seconds, only for people who may see it. */
export const useAgentBoard = (enabled: boolean) => {
  const live = useLiveConnected()
  return useQuery({
    queryKey: ['agent-flow', 'board'],
    queryFn: agentFlowApi.board,
    enabled,
    refetchInterval: pollMs(live, 2_000),
    refetchOnWindowFocus: true,
  })
}

/** The recorded story of a case, loaded only when someone opens the replay. */
export const useAgentReplay = (caseId: string | undefined) =>
  useQuery({
    queryKey: ['agent-flow', 'replay', caseId],
    queryFn: () => agentFlowApi.replay(caseId as string),
    enabled: !!caseId,
    staleTime: 30_000,
  })
