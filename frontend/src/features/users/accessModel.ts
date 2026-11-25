import type { PermissionGroup } from './types'

/**
 * The checkmarks on the access form, kept as a set of "module.level" ids (e.g. "stock.crud").
 * The server only knows permissions; these helpers translate in both directions.
 */
export type Ticked = ReadonlySet<string>

const idOf = (resource: string, level: string) => `${resource}.${level}`

/** Which boxes are ticked for a given set of permissions (a box is ticked when ALL it grants is held). */
export function tickedFromPermissions(catalog: PermissionGroup[], permissions: readonly string[]): Ticked {
  const held = new Set(permissions)
  const ticked = new Set<string>()
  for (const group of catalog) {
    for (const level of group.levels) {
      if (level.permissions.every((p) => held.has(p))) ticked.add(idOf(group.resource, level.key))
    }
  }
  return ticked
}

/** The permissions granted by the ticked boxes. */
export function permissionsFromTicked(catalog: PermissionGroup[], ticked: Ticked): string[] {
  const granted = new Set<string>()
  for (const group of catalog) {
    for (const level of group.levels) {
      if (ticked.has(idOf(group.resource, level.key))) level.permissions.forEach((p) => granted.add(p))
    }
  }
  return [...granted].sort()
}

/** Tick or untick one box. CRUD includes Read only, so ticking CRUD ticks Read only, and unticking Read only unticks CRUD. */
export function setLevel(group: PermissionGroup, ticked: Ticked, levelKey: string, on: boolean): Ticked {
  const next = new Set(ticked)
  if (on) {
    next.add(idOf(group.resource, levelKey))
    group.levels.find((l) => l.key === levelKey)?.implies.forEach((k) => next.add(idOf(group.resource, k)))
  } else {
    next.delete(idOf(group.resource, levelKey))
    // Anything that needs this box can't stay ticked without it.
    for (const other of group.levels) {
      if (other.implies.includes(levelKey)) next.delete(idOf(group.resource, other.key))
    }
  }
  return next
}

/** Quick presets for the whole form. */
export function preset(catalog: PermissionGroup[], mode: 'none' | 'read' | 'crud'): Ticked {
  const ticked = new Set<string>()
  if (mode === 'none') return ticked
  for (const group of catalog) {
    const read = group.levels.find((l) => l.key === 'read')
    const crud = group.levels.find((l) => l.key === 'crud')
    if (read) ticked.add(idOf(group.resource, read.key))
    if (mode === 'crud' && crud) ticked.add(idOf(group.resource, crud.key))
  }
  return ticked
}

export interface AccessSummary {
  label: string
  tone: 'admin' | 'full' | 'read' | 'custom' | 'none'
  /** One short line per module, for tooltips. */
  lines: string[]
}

/** A one-word description of what someone can do, plus the per-module detail. */
export function summarize(catalog: PermissionGroup[], permissions: readonly string[], isAdmin: boolean): AccessSummary {
  if (isAdmin) return { label: 'Administrator', tone: 'admin', lines: ['Full access, including managing users'] }

  const ticked = tickedFromPermissions(catalog, permissions)
  const lines: string[] = []
  let everythingCrud = true
  let everythingRead = true
  let anyCrud = false
  let anything = false

  for (const group of catalog) {
    const has = (key: string) => ticked.has(idOf(group.resource, key))
    const hasCrud = group.levels.some((l) => l.key === 'crud')
    const best = has('crud') ? 'CRUD' : has('read') ? 'Read only' : has('own') ? 'Own requests only' : null
    if (best) {
      lines.push(`${group.label}: ${best}`)
      anything = true
    }
    if (has('crud')) anyCrud = true
    if (!has('read')) everythingRead = false
    if (hasCrud ? !has('crud') : !has('read')) everythingCrud = false
  }

  if (!anything) return { label: 'No access', tone: 'none', lines }
  if (everythingCrud) return { label: 'Full CRUD', tone: 'full', lines }
  if (everythingRead && !anyCrud) return { label: 'Read only', tone: 'read', lines }
  const onlyOwn = lines.length === 1 && lines[0].endsWith('Own requests only')
  return { label: onlyOwn ? 'Own requests only' : 'Custom', tone: 'custom', lines }
}

/** Drops every box that grants something `held` doesn't include (you can't give access you don't have). */
export function limitTo(catalog: PermissionGroup[], ticked: Ticked, held: ReadonlySet<string>): Ticked {
  const next = new Set(ticked)
  for (const group of catalog) {
    for (const level of group.levels) {
      if (!level.permissions.every((p) => held.has(p))) next.delete(idOf(group.resource, level.key))
    }
  }
  return next
}
