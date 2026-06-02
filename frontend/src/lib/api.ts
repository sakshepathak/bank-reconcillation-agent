import axios, { AxiosError } from 'axios'

/**
 * Shared axios client.
 *
 * `withCredentials: true` is essential — without it the browser won't send
 * the httpOnly session cookie set by /api/v1/auth/login, so every request
 * would look unauthenticated.
 */
export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
})

/**
 * Wraps an axios error into a plain Error with the HTTP status attached.
 * Callers (and React Query) can check `err.status === 401` to react to
 * auth failures without dealing with axios internals.
 */
export class ApiError extends Error {
  status?: number
  detail?: unknown
  constructor(message: string, status?: number, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

api.interceptors.response.use(
  (r) => r,
  (err: AxiosError<{ detail?: string }>) => {
    const status = err.response?.status
    const detail = err.response?.data?.detail
    const msg =
      (typeof detail === 'string' && detail) || err.message || 'Unknown error'
    // Stay quiet about 401 from /auth/me — that's the expected "logged out" path.
    if (!(status === 401 && err.config?.url?.endsWith('/auth/me'))) {
      // eslint-disable-next-line no-console
      console.error('[API]', err.config?.url, status, msg)
    }
    return Promise.reject(new ApiError(msg, status, err.response?.data))
  },
)
