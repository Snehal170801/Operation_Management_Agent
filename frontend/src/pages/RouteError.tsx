import { isRouteErrorResponse, Link, useRouteError } from 'react-router-dom'
import { RefreshCw, TriangleAlert } from 'lucide-react'

/** What a person sees when a screen crashes while drawing itself. It replaces the library's default error page
 *  (which shows code to someone who can do nothing with it). The detail goes to the console for whoever is helping. */
export function RouteError() {
  const error = useRouteError()
  const missing = isRouteErrorResponse(error) && error.status === 404
  // eslint-disable-next-line no-console
  console.error('A screen crashed:', error)

  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center gap-4 px-4 py-16 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft text-brand-ink">
        <TriangleAlert size={26} />
      </span>
      <h1 className="text-xl font-semibold text-title">{missing ? 'Page not found' : 'Something went wrong on this page'}</h1>
      <p className="text-sm text-muted">
        {missing
          ? "That page doesn't exist or was moved."
          : "Nothing you did caused this, and your work is safe. Reloading usually fixes it. If it keeps happening, tell support what you were doing."}
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-white hover:opacity-90"
        >
          <RefreshCw size={15} /> Reload the page
        </button>
        <Link to="/" className="inline-flex h-10 items-center rounded-xl border border-line bg-white px-4 text-sm font-semibold text-title hover:bg-brand-tint">
          Go to home
        </Link>
      </div>
    </div>
  )
}
