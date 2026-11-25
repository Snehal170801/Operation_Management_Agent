import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div>
      <h1 className="page-title">Page not found</h1>
      <Link to="/" className="text-sm font-medium text-brand-ink hover:underline">
        Back to home
      </Link>
    </div>
  )
}
