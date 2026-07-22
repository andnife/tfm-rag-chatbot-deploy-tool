import { test, expect } from '@playwright/test'
import path from 'node:path'

// Visual confirmation of the Embed/Console toggle on the Widget config page.
const EMAIL = process.env.EXPLORE_EMAIL ?? 'explore@fake.com'
const PASSWORD = process.env.EXPLORE_PASSWORD ?? 'Explore1234'
const BOT_ID = process.env.EXPLORE_BOT_ID ?? ''
const OUT = path.resolve('demo-artifacts/widget-console')

test('widget page shows Embed/Console toggle and switches snippet', async ({ page }) => {
  test.skip(!BOT_ID, 'EXPLORE_BOT_ID not provided')

  await page.goto('/login')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Contraseña').fill(PASSWORD)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 })

  await page.goto(`/chatbots/${BOT_ID}/widget`)
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(1200)

  // Embed tab (default): a <script> tag snippet.
  const code = page.locator('pre').first()
  await expect(code).toContainText('<script')
  await expect(code).toContainText('data-tfm-widget')
  await page.screenshot({ path: path.join(OUT, 'ui-embed.png') })

  // Switch to Console tab: an IIFE snippet.
  await page.getByRole('tab', { name: 'Consola' }).click()
  await page.waitForTimeout(600)
  await expect(code).toContainText('document.createElement')
  await expect(code).toContainText('document.body.appendChild')
  await page.screenshot({ path: path.join(OUT, 'ui-console.png') })
})
