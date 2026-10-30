let csrfToken = ''

export function setCsrfToken(value) {
  csrfToken = value || ''
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (csrfToken && options.method && !['GET', 'HEAD'].includes(options.method)) {
    headers['X-CSRF-Token'] = csrfToken
  }
  const response = await fetch('/api' + path, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...options,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (!response.ok) {
    let detail = '请求失败'
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string'
        ? body.detail
        : body.detail?.map((item) => item.msg).join('；') || detail
    } catch {
      detail = response.statusText || detail
    }
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  if (response.status === 204) return null
  return response.json()
}

export function queryString(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value))
  }
  return search.toString()
}
