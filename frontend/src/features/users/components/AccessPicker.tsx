import clsx from 'clsx'
import { limitTo, permissionsFromTicked, preset, setLevel, tickedFromPermissions, type Ticked } from '../accessModel'
import { useDepartments } from '../hooks'
import type { PermissionGroup } from '../types'

export interface AccessValue {
  isAdmin: boolean
  ticked: Ticked
}

interface Props {
  catalog: PermissionGroup[]
  value: AccessValue
  onChange: (value: AccessValue) => void
  /** Only an administrator can make someone else an administrator. */
  canGrantAdmin: boolean
  /** What the person editing holds: nobody can tick a box that gives more than they have themselves. */
  actorPermissions: ReadonlySet<string>
}

const checkbox = 'h-4 w-4 accent-[#ea4d4e] disabled:cursor-not-allowed disabled:opacity-40'

/** One row per module, two ticks each (Read only / CRUD). Deliberately small: no roles, no long lists. */
export function AccessPicker({ catalog, value, onChange, canGrantAdmin, actorPermissions }: Props) {
  const { isAdmin, ticked } = value
  const departments = useDepartments().data ?? []
  const hasOwn = catalog.some((g) => g.levels.some((l) => l.key === 'own'))
  const held = new Set(permissionsFromTicked(catalog, ticked))
  // A department counts as "on" when everything it needs is ticked. A person can be in several.
  const isOn = (permissions: string[]) => permissions.every((p) => held.has(p))

  const toggleDepartment = (key: string) => {
    const target = departments.find((d) => d.key === key)
    if (!target) return
    const anyOn = departments.some((d) => isOn(d.permissions))
    // The first department picked replaces the form's default ticks; a second one adds to the first.
    const next = new Set(anyOn ? held : [])
    if (isOn(target.permissions)) {
      // Turning one off keeps whatever another department they are still in needs.
      const stillNeeded = new Set(departments.filter((d) => d.key !== key && isOn(d.permissions)).flatMap((d) => d.permissions))
      target.permissions.forEach((p) => !stillNeeded.has(p) && next.delete(p))
    } else {
      target.permissions.forEach((p) => next.add(p))
    }
    onChange({ isAdmin: false, ticked: limitTo(catalog, tickedFromPermissions(catalog, [...next]), actorPermissions) })
  }
  const grantable = (permissions: string[]) => permissions.every((p) => actorPermissions.has(p))

  const quick = (mode: 'none' | 'read' | 'crud') =>
    onChange({ isAdmin: false, ticked: limitTo(catalog, preset(catalog, mode), actorPermissions) })

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 text-xs font-medium text-muted">What can this user do?</legend>

      {canGrantAdmin && (
        <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-line bg-brand-tint/40 px-4 py-3 text-sm text-title">
          <input
            type="checkbox"
            checked={isAdmin}
            onChange={(e) => onChange({ isAdmin: e.target.checked, ticked })}
            className={clsx(checkbox, 'mt-0.5')}
          />
          <span>
            <span className="font-semibold">Administrator</span>
            <span className="block text-xs text-muted">Full access to everything, including managing users.</span>
          </span>
        </label>
      )}

      {isAdmin ? (
        <p className="rounded-xl bg-brand-tint px-4 py-3 text-xs text-brand-ink">
          Administrators can do everything, so there's nothing to tick.
        </p>
      ) : (
        <>
          {departments.length > 0 && (
            <div className="flex flex-col gap-2 rounded-xl border border-line bg-brand-tint/40 px-4 py-3">
              <p className="text-xs font-semibold text-title">Department</p>
              <p className="-mt-1 text-xs text-muted">Pick the team this person works in. Each team handles one agent. They can be in more than one.</p>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Departments">
                {departments.map((d) => {
                  const on = isOn(d.permissions)
                  return (
                    <button
                      key={d.key}
                      type="button"
                      aria-pressed={on}
                      title={`${d.agent}: ${d.handles}`}
                      onClick={() => toggleDepartment(d.key)}
                      className={clsx(
                        'rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
                        on ? 'border-brand bg-brand-soft text-brand-ink' : 'border-line bg-white text-title hover:bg-brand-tint',
                      )}
                    >
                      {d.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted">Quick set:</span>
            {(
              [
                ['none', 'None'],
                ['read', 'Read only'],
                ['crud', 'Full CRUD'],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => quick(mode)}
                className="rounded-lg border border-line bg-white px-3 py-1.5 font-medium text-title hover:bg-brand-tint"
              >
                {label}
              </button>
            ))}
          </div>

          <div className="overflow-hidden rounded-xl border border-line">
            <table className="w-full text-left text-sm">
              <thead className="bg-brand-tint text-xs text-title">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Area</th>
                  {hasOwn && <th className="w-24 px-2 py-2.5 text-center font-semibold">Own only</th>}
                  <th className="w-24 px-2 py-2.5 text-center font-semibold">Read only</th>
                  <th className="w-24 px-2 py-2.5 text-center font-semibold" title="Create, read, update and delete">CRUD</th>
                  <th className="w-44 px-2 py-2.5 text-center font-semibold" title="One specific action, ticked on its own">Specific action</th>
                </tr>
              </thead>
              <tbody>
                {catalog.map((group) => (
                  <tr key={group.resource} className="border-t border-line">
                    <td className="px-4 py-2.5 font-medium text-title">{group.label}</td>
                    {(hasOwn ? ['own', 'read', 'crud'] : ['read', 'crud']).map((key) => {
                      const level = group.levels.find((l) => l.key === key)
                      return (
                        <td key={key} className="px-2 py-2.5 text-center">
                          {level ? (
                            <input
                              type="checkbox"
                              className={checkbox}
                              checked={ticked.has(`${group.resource}.${key}`)}
                              disabled={!grantable(level.permissions)}
                              title={grantable(level.permissions) ? undefined : "You can't give access you don't have yourself"}
                              aria-label={`${group.label}: ${level.label}`}
                              onChange={(e) => onChange({ isAdmin, ticked: setLevel(group, ticked, key, e.target.checked) })}
                            />
                          ) : (
                            <span className="text-muted/40" aria-hidden="true">—</span>
                          )}
                        </td>
                      )
                    })}
                    <td className="px-2 py-2.5 text-center">
                      {group.levels
                        .filter((l) => !['own', 'read', 'crud'].includes(l.key))
                        .map((level) => (
                          <label key={level.key} className="inline-flex cursor-pointer items-center gap-2 text-xs text-title">
                            <input
                              type="checkbox"
                              className={checkbox}
                              checked={ticked.has(`${group.resource}.${level.key}`)}
                              disabled={!grantable(level.permissions)}
                              title={grantable(level.permissions) ? undefined : "You can't give access you don't have yourself"}
                              aria-label={`${group.label}: ${level.label}`}
                              onChange={(e) => onChange({ isAdmin, ticked: setLevel(group, ticked, level.key, e.target.checked) })}
                            />
                            {level.label}
                          </label>
                        ))}
                      {group.levels.every((l) => ['own', 'read', 'crud'].includes(l.key)) && (
                        <span className="text-muted/40" aria-hidden="true">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted">
            <b>Read only</b> = can look but not change. <b>CRUD</b> = can also create, update and delete. <b>Specific action</b> = one job, such as confirming goods or deciding invoices.
            {hasOwn && ' "Own only" = can send requests and see only their own.'}
          </p>
        </>
      )}
    </fieldset>
  )
}
