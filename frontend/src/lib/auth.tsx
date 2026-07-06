import { apiJson } from './api'

/**
 * Logout: ask the backend to clear the httpOnly cookie, then hard-redirect to /login.
 * Route protection is enforced by middleware.ts (cookie presence), so there is no
 * client-side isAuthenticated()/RequireAuth anymore — the httpOnly cookie is unreadable from JS.
 */
export async function logout(): Promise<void> {
  try {
    await apiJson('/auth/logout', 'POST')
  } catch {
    /* ignore: clear client navigation regardless of network result */
  }
  window.location.href = '/login'
}
