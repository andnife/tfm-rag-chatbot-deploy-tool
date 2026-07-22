import { describe, it, expect } from 'vitest'
import { buildEmbedSnippet, buildConsoleSnippet } from './widget-snippet'

const ORIGIN = 'https://host.example'
const KEY = 'wgt_abc123'

describe('buildEmbedSnippet', () => {
  it('produces a <script> tag with the widget src and data attributes', () => {
    const s = buildEmbedSnippet(ORIGIN, KEY)
    expect(s).toContain('<script')
    expect(s).toContain(`src="${ORIGIN}/widget/widget.js"`)
    expect(s).toContain(`data-public-key="${KEY}"`)
    expect(s).toContain(`data-api-base="${ORIGIN}"`)
    expect(s).toContain('data-tfm-widget="1"')
    expect(s).toContain('async')
    expect(s.trimEnd().endsWith('</script>')).toBe(true)
  })

  it('returns empty string without a public key', () => {
    expect(buildEmbedSnippet(ORIGIN, '')).toBe('')
  })
})

describe('buildConsoleSnippet', () => {
  it('produces an IIFE that injects a marked script element', () => {
    const s = buildConsoleSnippet(ORIGIN, KEY)
    expect(s).toContain('document.createElement')
    expect(s).toContain(`${ORIGIN}/widget/widget.js`)
    expect(s).toContain(KEY)
    expect(s).toContain('data-tfm-widget')
    expect(s).toContain('document.body.appendChild')
    // Single-line-ish, safe to paste in a console (no stray backticks).
    expect(s).not.toContain('`')
  })

  it('returns empty string without a public key', () => {
    expect(buildConsoleSnippet(ORIGIN, '')).toBe('')
  })
})
