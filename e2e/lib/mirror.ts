// Lifecycle for the nginx mirror that lets chat (>30s) work end-to-end.
// Routes /api+/widget straight to the backend with 600s timeouts; / to next.
import { execSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { MIRROR_CONTAINER, MIRROR_PORT } from './env'

const CONF = path.resolve(__dirname, '../../infra/nginx/e2e-mirror.conf')

function sh(cmd: string): string {
  return execSync(cmd, { stdio: ['ignore', 'pipe', 'pipe'] }).toString().trim()
}

async function reachable(): Promise<boolean> {
  try {
    const r = await fetch(`http://localhost:${MIRROR_PORT}/`, { redirect: 'manual' })
    return r.status > 0
  } catch {
    return false
  }
}

export async function startMirror(): Promise<void> {
  if (!existsSync(CONF)) throw new Error(`mirror config missing: ${CONF}`)
  try {
    sh(`docker rm -f ${MIRROR_CONTAINER}`)
  } catch {
    /* not running — fine */
  }
  sh(
    `docker run -d --name ${MIRROR_CONTAINER} ` +
      `--add-host=host.docker.internal:host-gateway -p ${MIRROR_PORT}:80 ` +
      `-v "${CONF}":/etc/nginx/nginx.conf:ro nginx:1.27-alpine`,
  )
  for (let i = 0; i < 30; i++) {
    if (await reachable()) return
    await new Promise((res) => setTimeout(res, 1000))
  }
  throw new Error(`nginx mirror did not become reachable on :${MIRROR_PORT}`)
}

export function stopMirror(): void {
  try {
    sh(`docker rm -f ${MIRROR_CONTAINER}`)
  } catch {
    /* already gone */
  }
}
