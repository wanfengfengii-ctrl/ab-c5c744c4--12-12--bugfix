// Thin client for the reconstruction API.  All calls go to the same origin
// (Vite proxies /api in development; FastAPI serves the built UI in prod).

export async function fetchHealth() {
  const r = await fetch('/api/health')
  if (!r.ok) throw new Error(`health ${r.status}`)
  return r.json()
}

/**
 * Submit a reconstruction request.
 * Returns { kind: 'result', body } for HTTP 200 (including status "none"),
 * or { kind: 'error', status, body } for 4xx responses.
 */
export async function reconstruct(payload) {
  const r = await fetch('/api/reconstruct', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = await r.json().catch(() => null)
  if (r.ok) return { kind: 'result', body }
  return { kind: 'error', status: r.status, body }
}
