# Widget delivery mode: Embed / Console toggle

**Date:** 2026-07-22
**Status:** approved (implementing)

## Problem

The Widget config page only offers the HTML **embed** snippet (`<script src=".../widget.js"
data-public-key=... data-api-base=... async>`), which requires editing the target site's
markup. For quick demos and injecting the widget on a page you don't control, we want a second
delivery mode: a snippet you paste into the **browser DevTools console** that injects the widget
into the current page live.

## Design

In the "Snippet de embed" card, replace the single code block with a **Tabs** toggle
(`Embed` | `Consola`) using the existing `@/components/ui/tabs` component. The active tab's
snippet is shown in the code block and copied by the copy button.

- **Embed** (unchanged): the current `<script … data-public-key … data-api-base … async>` tag.
- **Console**: a self-contained IIFE that creates a `<script>` element with the same
  `data-public-key` / `data-api-base`, marks it with `data-tfm-widget="1"`, and appends it to
  `document.body`:
  ```js
  (function(){var s=document.createElement('script');
   s.src="{origin}/widget/widget.js";
   s.setAttribute("data-public-key","{publicKey}");
   s.setAttribute("data-api-base","{origin}");
   s.setAttribute("data-tfm-widget","1");
   document.body.appendChild(s);})();
  ```

### widget.js change (the enabling fix)

`widget.js` currently reads config from `document.currentScript`, which is **`null` for
dynamically-injected scripts** — so a console-injected widget would abort. Fix with a fallback
selector that is backward compatible with the embed path (where `currentScript` still works):

```js
const SCRIPT_EL =
  document.currentScript ||
  document.querySelector('script[data-tfm-widget]') ||
  document.querySelector('script[data-public-key]');
```

Both the embed and console snippets carry `data-tfm-widget="1"` so the fallback reliably
selects the widget's own script tag.

## Scope (YAGNI)

- Frontend only + a 1-line `widget.js` fallback. **No backend changes.**
- Snippet construction extracted to pure helpers (`buildEmbedSnippet`, `buildConsoleSnippet`)
  so they are unit-testable without rendering the page.

## Caveat (documented in the Console tab hint)

The console snippet loads `widget.js` from `http://localhost` (or the app origin). On a real
**HTTPS** site the browser blocks it as **mixed content**. It works on local/http pages — which
is the intended use for the live demo of the widget on "a separate web page".

## Testing

- **Unit (vitest):** `buildEmbedSnippet` / `buildConsoleSnippet` produce the expected strings
  from `(origin, publicKey)`.
- **e2e (Playwright):** inject the console snippet into a blank page and assert the widget
  bubble renders (regression for the `currentScript` fallback).
