import { test, expect, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

// Exploratory crawl of every reachable route as a throwaway account, to surface
// anything odd (JS errors, failed requests, blank pages, redirects) with a
// fully-loaded screenshot per route. Never sends a chat message.

const EMAIL = process.env.EXPLORE_EMAIL ?? 'explore@fake.com'
const PASSWORD = process.env.EXPLORE_PASSWORD ?? 'Explore1234'
const KB_ID = process.env.EXPLORE_KB_ID ?? ''
const BOT_ID = process.env.EXPLORE_BOT_ID ?? ''

const OUT = path.resolve('demo-artifacts/explore')
const SHOTS = path.join(OUT, 'shots')
mkdirSync(SHOTS, { recursive: true })

type Anomaly = { route: string; kind: string; detail: string }
const anomalies: Anomaly[] = []

// Benign noise to ignore (dev-only warnings, favicon, HMR, react devtools).
const IGNORE = [
  /favicon/i,
  /react-devtools/i,
  /_next\/static\/webpack\/.*hot-update/i,
  /Download the React DevTools/i,
  /\[Fast Refresh\]/i,
]
const ignored = (s: string): boolean => IGNORE.some((re) => re.test(s))

test('exploratory crawl — all reachable routes', async ({ page }) => {
  let current = 'login'
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !ignored(msg.text())) {
      anomalies.push({ route: current, kind: 'console.error', detail: msg.text().slice(0, 300) })
    }
  })
  page.on('pageerror', (err) => {
    if (!ignored(err.message)) {
      anomalies.push({ route: current, kind: 'pageerror', detail: err.message.slice(0, 300) })
    }
  })
  page.on('response', (res) => {
    const s = res.status()
    if (s >= 400 && !ignored(res.url())) {
      anomalies.push({
        route: current,
        kind: `http ${s}`,
        detail: `${res.request().method()} ${res.url().replace(/^https?:\/\/[^/]+/, '')}`,
      })
    }
  })

  // ── Login ─────────────────────────────────────────────────────────────────
  await page.goto('/login')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Contraseña').fill(PASSWORD)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 })

  const routes: { name: string; url: string }[] = [
    { name: 'dashboard', url: '/dashboard' },
    { name: 'knowledge-list', url: '/knowledge' },
    { name: 'knowledge-new', url: '/knowledge/new' },
    { name: 'knowledge-detail', url: `/knowledge/${KB_ID}` },
    { name: 'chatbots-list', url: '/chatbots' },
    { name: 'chatbots-new', url: '/chatbots/new' },
    { name: 'chatbot-edit', url: `/chatbots/${BOT_ID}/edit` },
    { name: 'chatbot-playground', url: `/chatbots/${BOT_ID}/playground` },
    { name: 'chatbot-widget', url: `/chatbots/${BOT_ID}/widget` },
    { name: 'chatbot-sessions', url: `/chatbots/${BOT_ID}/sessions` },
    { name: 'settings-credentials', url: '/settings/credentials' },
    { name: 'inspect', url: '/inspect' },
    { name: 'admin-eval', url: '/admin/eval' },
    { name: 'admin-users', url: '/admin/users' },
  ]

  let i = 0
  for (const r of routes) {
    i += 1
    current = r.name
    try {
      await page.goto(r.url, { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await page.waitForLoadState('networkidle').catch(() => {})
      await page.waitForTimeout(1500) // settle for client render

      const finalUrl = new URL(page.url()).pathname
      if (finalUrl !== r.url && !r.url.includes(finalUrl)) {
        anomalies.push({ route: r.name, kind: 'redirect', detail: `${r.url} → ${finalUrl}` })
      }

      // Blank-page heuristic: main content area essentially empty.
      const bodyText = (await page.locator('main, body').first().innerText().catch(() => '')) || ''
      if (bodyText.trim().length < 20) {
        anomalies.push({ route: r.name, kind: 'blank-ish', detail: `body text len=${bodyText.trim().length}` })
      }

      await page.screenshot({
        path: path.join(SHOTS, `${String(i).padStart(2, '0')}-${r.name}.png`),
        fullPage: true,
      })
    } catch (e: unknown) {
      anomalies.push({ route: r.name, kind: 'nav-error', detail: String(e).slice(0, 300) })
    }
  }

  // Write the anomaly report.
  const byRoute: Record<string, Anomaly[]> = {}
  for (const a of anomalies) (byRoute[a.route] ??= []).push(a)
  const lines: string[] = ['# Exploratory crawl — anomalies', '']
  if (anomalies.length === 0) lines.push('No anomalies detected. ✅')
  for (const [route, items] of Object.entries(byRoute)) {
    lines.push(`## ${route}`)
    for (const it of items) lines.push(`- **${it.kind}**: ${it.detail}`)
    lines.push('')
  }
  writeFileSync(path.join(OUT, 'anomalies.md'), lines.join('\n'))

  console.log('\n================ ANOMALY REPORT ================')
  console.log(lines.join('\n'))
  console.log('===============================================\n')
  console.log(`Screenshots: ${SHOTS}`)
})
