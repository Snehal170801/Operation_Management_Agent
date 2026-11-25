import clsx from 'clsx'
import { motion } from 'motion/react'
import { AGENT_ICON, ORB_STYLE, PILL_STYLE, STATE_STYLE } from '../agentStyle'
import type { AgentNode } from '../types'

/** The agent the story is about: the one working, otherwise the one that needs attention or is waiting. */
function focusAgent(agents: AgentNode[]): AgentNode | undefined {
  return (
    agents.find((a) => a.state === 'working') ??
    agents.find((a) => a.state === 'needs_person' || a.state === 'failed') ??
    agents.find((a) => a.state === 'waiting')
  )
}

/** One sentence that says what is happening right now, with the agent it is about. Used on the stage header
 *  (live page and replay). A new sentence fades in over the old one's place, so it never flashes blank. */
export function StoryLine({ agents, headline, nextStep }: { agents: AgentNode[]; headline: string; nextStep?: string | null }) {
  const agent = focusAgent(agents)
  const Icon = agent ? AGENT_ICON[agent.key] : null
  return (
    <div className="mt-3 flex items-start gap-4">
      {agent && Icon && (
        <span className={clsx('mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-full', ORB_STYLE[agent.state])} aria-hidden>
          <Icon size={20} strokeWidth={1.9} />
        </span>
      )}
      <div className="min-w-0">
        {agent && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-white/80">{agent.name}</span>
            <span className={clsx('rounded-full px-2.5 py-0.5 text-[11px] font-semibold', PILL_STYLE[agent.state])}>{STATE_STYLE[agent.state].word}</span>
          </div>
        )}
        <motion.h2
          key={headline}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: 'easeOut' }}
          className="mt-1 text-xl font-semibold leading-snug text-white sm:text-2xl"
          role="status"
        >
          {headline}
        </motion.h2>
        {nextStep && (
          <motion.p
            key={nextStep}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="mt-1.5 text-sm text-slate-400"
          >
            <span className="font-semibold text-white/60">Next:</span> {nextStep}
          </motion.p>
        )}
      </div>
    </div>
  )
}
