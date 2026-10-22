import { Link } from 'react-router-dom'
import { Empty } from '../../ui'
export default function NotFound() {
  return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><Empty title="Page not found" action={<Link className="btn primary" to="/">Go to the home page</Link>}>The address may have changed, or the link was copied incompletely.</Empty></div>
}
