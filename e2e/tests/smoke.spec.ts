import { test, expect } from '@playwright/test'

const EMAIL = process.env.E2E_EMAIL ?? 'debug@test.com'
const PASSWORD = process.env.E2E_PASSWORD ?? 'debug1234'
const CHATBOT_ID = '9b39380c-540e-43e9-a0ab-39ca108120b0'

test('happy path: login → knowledge → chatbots → playground chat', async ({ page }) => {
  // ── Step 1: Login ──────────────────────────────────────────────────────────
  await page.goto('/login')

  // The login form uses <Label htmlFor="email"> and <Label htmlFor="password">
  // so getByLabel matches by the label's text content associated to the input id.
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Contraseña').fill(PASSWORD)
  // Submit button text is "Entrar"
  await page.getByRole('button', { name: 'Entrar' }).click()

  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })

  // ── Step 2: Knowledge Bases list ───────────────────────────────────────────
  await page.goto('/knowledge')
  // AppShell renders the page title as <h1> in the Topbar; t('kb.title') = 'Knowledge Bases'
  await expect(page.getByRole('heading', { name: 'Knowledge Bases' })).toBeVisible({ timeout: 15_000 })

  // ── Step 3: Chatbots list ──────────────────────────────────────────────────
  await page.goto('/chatbots')
  // t('chatbots.title') = 'Chatbots'
  await expect(page.getByRole('heading', { name: 'Chatbots' })).toBeVisible({ timeout: 15_000 })
  // Also verify the list has at least one chatbot card (each card has a "Probar" button)
  await expect(page.getByRole('link', { name: /Probar/ }).first()).toBeVisible({ timeout: 15_000 })

  // ── Step 4: Playground – type a question and get an assistant response ─────
  await page.goto(`/chatbots/${CHATBOT_ID}/playground`)
  // The ChatComposer uses a <Textarea placeholder="Escribe tu mensaje...">
  const input = page.getByPlaceholder('Escribe tu mensaje...')
  await expect(input).toBeVisible({ timeout: 10_000 })
  await input.fill('¿Qué arquitectura usa la plataforma?')

  // Send button is an icon-only button (no text), next to the textarea.
  // The button has <Send> icon inside. Click via its position relative to the textarea.
  // We match the submit button that is a sibling: role="button" near the textarea.
  // The ChatComposer renders: <Textarea> + <Button size="icon" onClick={submit}>.
  // Use a locator scoped to the composer's parent flex div.
  const composer = page.locator('div.flex.gap-2.items-end').last()
  await composer.getByRole('button').click()

  // Wait for an assistant response. While the LLM is running the playground shows
  // a pending bubble: {chat.isPending && <ChatMessage role="assistant" content="..." />}
  // When the response arrives, chat.isPending flips false (the "..." bubble disappears)
  // and the turns array gets the real assistant Turn with actual content.
  //
  // Strategy: wait for a justify-start bubble that has text longer than 3 chars
  // (i.e. not just "..."). The LLM on CPU is slow: ~3–4 min warm, and measured up
  // to ~7 min on a loaded machine (the agentic pipeline does retrieval + LLM calls).
  // Use a 600s timeout to tolerate that worst case (matches nginx proxy_read_timeout).
  // We poll for the condition with page.waitForFunction rather than a locator assertion
  // so we can express "text length > 3".
  await page.waitForFunction(
    () => {
      const bubbles = document.querySelectorAll('div.justify-start div.whitespace-pre-wrap')
      for (const b of bubbles) {
        const txt = b.textContent?.trim() ?? ''
        if (txt.length > 3) return true
      }
      return false
    },
    undefined,
    { timeout: 600_000 },
  )
  // Confirm the visible bubble is non-trivial
  const assistantBubble = page.locator('div.justify-start div.whitespace-pre-wrap').first()
  await expect(assistantBubble).toBeVisible()
})
