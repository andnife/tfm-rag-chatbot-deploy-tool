import { test, expect, type Page, type Locator } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

// End-to-end validation of the defense demo, following docs/DEMO-RUNBOOK.md.
// Uses the pre-provisioned demo account and the "Asistente Universidad Europea"
// chatbot. Records video + numbered screenshots for human review.

const EMAIL = 'demo@fake.com'
const PASSWORD = 'Demo1234'
const BOT_ID = '3ff4ec3c-8c24-487f-ae0b-45f731a1b416'
const KB_ID = '269a91ee-fb60-49ac-a324-7638b22345d5'

// 5 questions: 4 documental (must cite sources) + 1 honest abstention.
const QUESTIONS: { q: string; expectCitations: boolean }[] = [
  { q: '¿Qué becas ofrece la universidad por buen expediente académico?', expectCitations: true },
  { q: '¿En qué ciudades tiene campus la Universidad Europea?', expectCitations: true },
  { q: '¿Ofrecen algún grado en Inteligencia Artificial? ¿En qué campus?', expectCitations: true },
  { q: '¿Cuáles son los pasos del proceso de admisión?', expectCitations: true },
  { q: '¿Quién es el rector actual de la universidad?', expectCitations: false }, // abstention
]

const SHOTS = path.resolve('demo-artifacts/shots')
mkdirSync(SHOTS, { recursive: true })
let step = 0
async function shot(page: Page, name: string): Promise<void> {
  step += 1
  // Let the client finish rendering before capturing: no in-flight requests
  // plus a short settle for React to paint the fetched data.
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(1200)
  await page.screenshot({
    path: path.join(SHOTS, `${String(step).padStart(2, '0')}-${name}.png`),
    fullPage: false,
  })
}

// Send a question and wait for a real assistant answer (a non-"..." bubble
// whose count grew by one). Returns the new answer's locator + text.
async function ask(
  page: Page,
  question: string,
): Promise<{ bubble: Locator; text: string }> {
  const bubbles = page.locator('div.justify-start div.whitespace-pre-wrap')
  const before = await bubbles.count()

  const composer = page.getByPlaceholder('Escribe tu mensaje...')
  await composer.click()
  await composer.fill(question)
  await composer.press('Enter')

  // Wait until a NEW assistant bubble exists and it is no longer the "..."
  // streaming placeholder.
  await expect
    .poll(
      async () => {
        const n = await bubbles.count()
        if (n <= before) return '...'
        return (await bubbles.nth(n - 1).innerText()).trim()
      },
      { timeout: 120_000, intervals: [1000] },
    )
    .not.toMatch(/^(\.\.\.|)$/)

  const bubble = bubbles.nth((await bubbles.count()) - 1)
  // Bring the fresh answer (and its citations block) into view before shots.
  await bubble.scrollIntoViewIfNeeded().catch(() => {})
  return { bubble, text: (await bubble.innerText()).trim() }
}

test('demo runbook — walkthrough with 5 questions (citations + abstention)', async ({
  page,
}) => {
  // ── 1. Login ────────────────────────────────────────────────────────────
  await page.goto('/login')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Contraseña').fill(PASSWORD)
  await shot(page, 'login-filled')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 })
  // Wait for real dashboard content, not the empty shell.
  await expect(page.getByText(/Chatbots/i).first()).toBeVisible({ timeout: 20_000 })
  await shot(page, 'dashboard')

  // ── 2. Credentials ────────────────────────────────────────────────────────
  await page.goto('/settings/credentials')
  await expect(page.getByText(/deepinfra/i).first()).toBeVisible({ timeout: 20_000 })
  await shot(page, 'credentials')

  // ── 3. Knowledge base (4 ingested docs) ───────────────────────────────────
  await page.goto(`/knowledge/${KB_ID}`)
  await expect(page.getByText(/Universidad Europea/i).first()).toBeVisible({
    timeout: 20_000,
  })
  // Wait for at least one ingested source row to render.
  await expect(page.getByText(/\.txt|\.pdf|\.docx/i).first()).toBeVisible({
    timeout: 20_000,
  })
  await shot(page, 'knowledge-base')

  // ── 4. Chatbot config + widget snippet ────────────────────────────────────
  await page.goto(`/chatbots/${BOT_ID}/edit`)
  await expect(page.getByText(/Asistente Universidad Europea/i).first()).toBeVisible({
    timeout: 20_000,
  })
  await shot(page, 'chatbot-edit')

  await page.goto(`/chatbots/${BOT_ID}/widget`)
  await expect(page.getByText(/script|data-|widget/i).first()).toBeVisible({
    timeout: 20_000,
  })
  await shot(page, 'widget-snippet')

  // ── 5. Playground — the climax ────────────────────────────────────────────
  await page.goto(`/chatbots/${BOT_ID}/playground`)
  await expect(page.getByPlaceholder('Escribe tu mensaje...')).toBeVisible({
    timeout: 20_000,
  })
  await shot(page, 'playground-empty')

  for (let i = 0; i < QUESTIONS.length; i++) {
    const { q, expectCitations } = QUESTIONS[i]
    const { text } = await ask(page, q)
    console.log(`\n[Q${i + 1}${expectCitations ? ' documental' : ' abstención'}] ${q}\n${text}\n`)
    expect(text.length).toBeGreaterThan(15)
    await shot(page, `q${i + 1}-${expectCitations ? 'documental' : 'abstencion'}`)

    if (!expectCitations) {
      // Honest abstention: reads as a polite refusal, not a fabricated answer.
      expect(text.toLowerCase()).toMatch(
        /no (dispongo|tengo|cuento|puedo)|no se encuentra|no aparece|no está|admisiones/i,
      )
    }
  }

  // At least the documental answers must have surfaced a citations block.
  await expect(page.getByText('Fuentes').first()).toBeVisible({ timeout: 10_000 })
  await shot(page, 'final')
})
