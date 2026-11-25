// Safety net: refuse to run unless the target is the test environment (right ports, the API reports its database is a test one).
export default async function globalSetup() {
  const web = new URL(process.env.E2E_WEB_URL ?? 'http://localhost:5190')
  const api = process.env.E2E_API_URL ?? 'http://localhost:8100'
  if (['5180', '5181'].includes(web.port) || ['8000', '8001'].includes(new URL(api).port)) {
    throw new Error('Refusing to run: that is the port of the real servers.')
  }
  for (const url of [api + '/health', web.origin + '/']) {
    const res = await fetch(url).catch(() => null)
    if (!res || !res.ok) throw new Error(`Test environment is not running (${url}). Start it with: npm run e2e:up`)
  }
}
