import { test, expect } from '@playwright/test'

// Simulates pasting the "Console" snippet into DevTools on a page that does NOT
// have the widget <script> in its markup. This is the case where
// document.currentScript is null; the widget must locate its tag via the
// data-tfm-widget fallback and still mount (#tfm-widget-host).

const PUBLIC_KEY = process.env.EXPLORE_PUBLIC_KEY ?? ''

test('console snippet mounts the widget via the currentScript fallback', async ({ page }) => {
  test.skip(!PUBLIC_KEY, 'EXPLORE_PUBLIC_KEY not provided')

  // A real same-origin page (avoids mixed-content / cross-origin for the demo).
  await page.goto('/login')
  const origin = new URL(page.url()).origin

  // The exact shape produced by buildConsoleSnippet(origin, key), eval'd in the
  // page as if pasted into the console.
  const snippet = `(function(){var s=document.createElement('script');s.src="${origin}/widget/widget.js";s.setAttribute("data-public-key","${PUBLIC_KEY}");s.setAttribute("data-api-base","${origin}");s.setAttribute("data-tfm-widget","1");document.body.appendChild(s);})();`
  await page.evaluate((code) => {
    // eslint-disable-next-line no-eval
    ;(0, eval)(code)
  }, snippet)

  // The widget only mounts its shadow host if it resolved its <script> element
  // (the fallback) AND the public key — the exact regression we care about.
  await expect(page.locator('#tfm-widget-host')).toBeAttached({ timeout: 30_000 })

  // And the bubble renders inside the shadow root.
  const bubble = page.locator('#tfm-widget-host').locator('.bubble')
  await expect(bubble).toBeVisible({ timeout: 15_000 })

  await page.waitForTimeout(1000)
  await page.screenshot({ path: 'demo-artifacts/widget-console/injected.png' })
})
