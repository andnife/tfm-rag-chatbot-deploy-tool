import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
// Side-effect import: initializes i18next (ES default, EN catalog available)
// exactly like app/providers.tsx does for the real app.
import '@/lib/i18n'

// Unmount React trees between tests so effects/timers from one test don't
// leak into the next (React Testing Library does not do this automatically
// outside of the Jest auto-cleanup integration).
afterEach(() => {
  cleanup()
})

// ---- jsdom polyfills for Radix UI --------------------------------------
//
// Radix's Select/Dialog primitives call a handful of browser APIs that
// jsdom does not implement. Without these, interacting with <Select> in
// tests throws (`target.hasPointerCapture is not a function`) or silently
// no-ops (`scrollIntoView`).
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof window.ResizeObserver === 'undefined') {
  window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {}
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {}
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
