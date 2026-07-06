import { test, expect } from '@playwright/test'
import { E2E_EMAIL } from '../../lib/env'

// Area G — inspect (read-only debug page renders account + tables).
test('G · inspect page renders account/tenant info', async ({ page }) => {
  await page.goto('/inspect')
  // The e2e user's email is shown in the Account & Tenant card.
  await expect(page.getByText(E2E_EMAIL, { exact: false })).toBeVisible({ timeout: 15_000 })
})
