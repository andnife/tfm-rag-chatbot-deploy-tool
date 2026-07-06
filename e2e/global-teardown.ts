// Runs once after the suite: delete everything the e2e tenant created, then stop
// the mirror. Best-effort — never fails the run.
import { ApiClient } from './lib/api-client'
import { stopMirror } from './lib/mirror'
import { E2E_EMAIL, E2E_PASSWORD } from './lib/env'

export default async function globalTeardown(): Promise<void> {
  try {
    const api = new ApiClient()
    await api.login(E2E_EMAIL, E2E_PASSWORD)
    const bots = (await api.listChatbots()) as Array<{ id: string }>
    for (const b of bots) await api.deleteChatbot(b.id).catch(() => {})
    const kbs = (await api.listKBs()) as Array<{ id: string }>
    for (const k of kbs) await api.deleteKB(k.id).catch(() => {})
    const creds = (await api.listCredentials()) as Array<{ id: string; provider_id: string }>
    for (const c of creds) if (c.provider_id !== 'ollama') await api.deleteCredential(c.id).catch(() => {})
  } catch {
    /* best-effort cleanup */
  } finally {
    stopMirror()
  }
}
