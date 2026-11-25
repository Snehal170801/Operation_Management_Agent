import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, RotateCcw } from 'lucide-react'
import clsx from 'clsx'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { QueryState } from '@/components/ui/QueryState'
import { formatDate, formatDateTime } from '@/lib/format'
import { useAgentInfoAt, useAgentReplay } from '../hooks'
import { AgentDialog } from './AgentDialog'
import { FlowDiagram } from './FlowDiagram'
import { JourneyBar } from './JourneyBar'
import { RequestCard } from './RequestCard'
import { StoryLine } from './StoryLine'
import { SupportStrip } from './SupportStrip'
import type { AgentKey, FlowActivity, ReplayFrame } from '../types'

const SPEEDS = [0.5, 1, 2] as const

/** How long to stay on a moment (at 1x): long enough to read the line and to see the animation finish, and
 *  longer when an agent changes state (starts, finishes, hands over), which is the part worth watching. */
function dwell(frame: ReplayFrame, previous: ReplayFrame | undefined, index: number): number {
  const reading = 1500 + (frame.event ? frame.event.text.length * 40 : 0)
  const changed = !previous || frame.agents.some((a, i) => a.state !== previous.agents[i]?.state)
  return reading + (changed ? 1200 : 0) + (index === 0 ? 1000 : 0)
}

const DOT = { info: 'bg-brand', ok: 'bg-[#16A34A]', warn: 'bg-amber-500', bad: 'bg-danger' } as const

/** Plays a case's story back, moment by moment, with the same animated pipeline as the live page.
 *  Time between moments is compressed (a case that took two days replays in seconds). */
function ReplayPlayerView({ caseId, onClose, autoPlay = false }: { caseId: string; onClose: () => void; autoPlay?: boolean }) {
  const replay = useAgentReplay(caseId)
  const frames = useMemo(() => replay.data?.frames ?? [], [replay.data])
  const last = Math.max(0, frames.length - 1)

  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(autoPlay)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const top = useRef<HTMLDivElement>(null)
  const [openAgent, setOpenAgent] = useState<AgentKey>()

  // The Play button is lower on the page than the stage, so bring the player into view when it opens.
  useEffect(() => {
    top.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  // Playing stops by itself at the last moment (derived, not stored).
  const running = playing && index < last

  // How long this moment stays on screen. The progress line fills over exactly this long, so it moves
  // continuously like a video's playhead instead of jumping from moment to moment.
  const wait = running ? dwell(frames[index], frames[index - 1], index) / speed : 0

  useEffect(() => {
    if (!running) return
    timer.current = setTimeout(() => setIndex((i) => Math.min(last, i + 1)), wait)
    return () => clearTimeout(timer.current)
  }, [running, index, last, wait])

  function onPlay() {
    if (index >= last) setIndex(0) // pressing play at the end starts over
    setPlaying(!running)
  }

  const frame = frames[index]
  // What the agent had done up to this moment, newest first (the replay never shows the future).
  const happened = frames.slice(0, index + 1).flatMap((f) => (f.event ? [f.event] : [])).reverse() as FlowActivity[]
  const dialogAgent = frame?.agents.find((a) => a.key === openAgent)
  // The agent's full account as it was at this moment (supplier replies, ranking, checks...), not as it ended up.
  const agentInfo = useAgentInfoAt(caseId, openAgent, frame?.at)

  return (
    <div ref={top} className="scroll-mt-4">
    <Card title="Replay" action={
        <span className="inline-flex items-center gap-3">
          {frames.length > 0 && <span>Moment {index + 1} of {frames.length}</span>}
          <button type="button" onClick={onClose} className="font-medium text-brand-ink hover:underline">
            Back to live
          </button>
        </span>
      }>
      <QueryState variant="detail" rows={4} isLoading={replay.isLoading} error={replay.error} isEmpty={!frames.length}
        emptyMessage="There is nothing to replay for this case yet.">
        {frame && (
          <div className="flex flex-col gap-5">
            <FlowDiagram
              agents={frame.agents}
              footer={<><JourneyBar agents={frame.agents} /><SupportStrip support={frame.support} /></>}
              header={<StoryLine agents={frame.agents} headline={frame.headline} nextStep={frame.next_step} />}
              onSelect={(a) => {
                setPlaying(false) // stop where it is, so the details can be read
                setOpenAgent(a.key)
              }}
            />

            <div key={index} className="dash-fade-in flex min-h-14 items-center gap-3 rounded-xl bg-brand-tint px-5 py-3.5 text-base" aria-live="polite">
              {frame.event && <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', DOT[frame.event.tone])} />}
              <span className="min-w-0 flex-1">
                {frame.event ? (
                  <>
                    <b className="text-title">{frame.event.agent}</b> <span className="text-muted">· {frame.event.text}</span>
                  </>
                ) : (
                  <span className="text-muted">{frame.headline}</span>
                )}
              </span>
              <span className="shrink-0 text-sm text-muted">{formatDateTime(frame.at)}</span>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={onPlay}>
                {running ? <Pause size={16} /> : <Play size={16} />} {running ? 'Pause' : index >= last ? 'Replay' : 'Play'}
              </Button>
              <Button variant="secondary" onClick={() => { setPlaying(false); setIndex(0) }} aria-label="Back to the start">
                <RotateCcw size={16} />
              </Button>
              <div className="relative flex h-6 min-w-40 flex-1 items-center">
                <div className="relative h-2 w-full overflow-hidden rounded-full bg-line">
                  <div
                    className="h-full rounded-full bg-brand"
                    style={{
                      width: `${(Math.min(last, index + (running ? 1 : 0)) / Math.max(1, last)) * 100}%`,
                      transition: running ? `width ${wait}ms linear` : 'width 250ms ease-out',
                    }}
                  />
                </div>
                <input
                  type="range" min={0} max={last} value={index} aria-label="Replay position"
                  onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)) }}
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                />
              </div>
              <div className="flex rounded-xl border border-line bg-white p-1" role="group" aria-label="Speed">
                {SPEEDS.map((s) => (
                  <button key={s} type="button" onClick={() => setSpeed(s)} aria-pressed={speed === s}
                    className={clsx('h-8 rounded-lg px-3 text-xs font-semibold', speed === s ? 'bg-brand-soft text-brand-ink' : 'text-muted hover:bg-brand-tint')}>
                    {s}x
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </QueryState>
    </Card>
    {dialogAgent && (
      <AgentDialog
        agent={dialogAgent}
        activity={happened}
        info={agentInfo.data}
        infoLoading={agentInfo.isLoading}
        expectedDelivery={replay.data?.expected_delivery}
        staff={replay.data?.audience === 'staff'}
        now={0}
        when="time"
        onClose={() => setOpenAgent(undefined)}
      />
    )}
    {frame && <div className="mt-5"><RequestCard request={replay.data?.request} rows={replay.data?.expected_delivery ? [['Expected delivery', formatDate(replay.data.expected_delivery)]] : []} /></div>}
    </div>
  )
}

// The page re-renders every second (clocks) and every two seconds (live data); the player must not.
export const ReplayPlayer = memo(ReplayPlayerView)
