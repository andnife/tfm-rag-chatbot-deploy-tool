// Builders for the two widget delivery snippets shown on the Widget config page.
// Kept as pure functions (no DOM / React) so they are unit-testable.
//
// Both snippets carry data-tfm-widget="1" so widget.js can locate its own
// <script> element via a fallback selector when document.currentScript is null
// (the case for the console-injected snippet).

export function buildEmbedSnippet(origin: string, publicKey: string): string {
  if (!publicKey) return ''
  return `<script
  src="${origin}/widget/widget.js"
  data-public-key="${publicKey}"
  data-api-base="${origin}"
  data-tfm-widget="1"
  async
></script>`
}

export function buildConsoleSnippet(origin: string, publicKey: string): string {
  if (!publicKey) return ''
  // Self-contained IIFE: creates a marked <script> element and appends it to
  // the current page. Paste into the browser DevTools console.
  return `(function(){var s=document.createElement('script');s.src="${origin}/widget/widget.js";s.setAttribute("data-public-key","${publicKey}");s.setAttribute("data-api-base","${origin}");s.setAttribute("data-tfm-widget","1");document.body.appendChild(s);})();`
}
