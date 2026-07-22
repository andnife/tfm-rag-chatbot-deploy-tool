# Differentiate OpenAI vs OpenAI-compatible credentials

**Date:** 2026-07-22
**Status:** approved (decisions locked) — implement on request

## Problem

Adding an "OpenAI" credential and an "OpenAI-compatible" credential looks identical in the UI:
the Add-credential dialog always shows the `base_url` and both concurrency fields regardless of
provider. The two should differ:

- **OpenAI**: no `base_url` prompt (the endpoint is fixed) and OpenAI's recommended rate limits
  applied automatically (not prompted).
- **OpenAI-compatible**: `base_url` mandatory, concurrency config offered (as today).

## Finding (scope is smaller than it looks)

The **backend already distinguishes** the two, centrally, in
`application/integrations/endpoint_resolver.py`:

- `openai` → `base_url` forced to `https://api.openai.com/v1` (any stored value ignored).
- `openai_compat` → `base_url` required (`ValidationError` if missing); `upsert` also validates
  via the descriptor's `requires_base_url_input`.

The catalog (`domain/catalog/llm_providers.py`) already sets `openai.requires_base_url_input =
False` / `openai_compat = True`, with `default_models` only for OpenAI.

**The real gap is the frontend** (`AddCredentialDialog`), which ignores the provider descriptor,
plus the absence of provider-specific recommended rate limits.

## Design

### 1. Frontend — provider-aware Add/Edit credential dialog (the bulk)

Read the selected provider's descriptor (already returned by the providers endpoint:
`requires_base_url_input`, `display_name`, `config_source`).

- **base_url**: render and require it only when `requires_base_url_input` is true
  (`openai_compat`). Hidden for `openai`. Zod validation is conditioned on the selected provider
  (base_url required ⇔ `requires_base_url_input`).
- **Concurrency fields** (`max_concurrency`, `min_request_interval_seconds`):
  - `openai_compat`: shown and **optional** — same as today (placeholder/hint; empty ⇒ default).
  - `openai`: **hidden**; the backend applies OpenAI's recommended defaults.
- Apply the same conditional logic to the edit-credential flow (verify whether it shares
  `AddCredentialDialog` or is a separate component; unify if trivial).

### 2. Backend — recommended rate limits for OpenAI (eval-only)

- Extend `LLMProviderDescriptor` with:
  - `recommended_max_concurrency: int | None` — `openai = 8`, `openai_compat = None`, `ollama = None`.
  - `recommended_min_request_interval_seconds: float | None` — all `None` (no interval).
- **Consumer precedence** (RAGAS judge rate limits, `infrastructure/evaluation/ragas_evaluator.py`
  wiring): explicit credential value → provider `recommended_*` → global default
  (`RAGAS_MAX_WORKERS`).
- **Scope: evaluation only.** Live chat is *not* throttled by these values (it is naturally
  serialized per request). Per the product decision, a credential's rate limits are a
  configuration/safety layer — most relevant to eval runs and to future multi-user/multi-instance
  concurrency — not a global app-wide throttle.
- (Optional cleanup) On `upsert` of an `openai` credential, ignore any submitted `base_url` so no
  dead value is persisted (the resolver forces the canonical URL anyway).

## Out of scope

- Throttling live chat generation with these limits.
- Per-model / tier-aware OpenAI limits (RPM/TPM). A single conservative concurrency (8) is enough;
  429s are already retried.

## Testing

- **Unit (backend):** descriptor exposes the recommended defaults; rate-limit resolution honours
  the precedence (credential → recommended → global).
- **Unit (frontend, vitest):** the dialog renders base_url + concurrency for `openai_compat` and
  hides them for `openai`; base_url is required only for `openai_compat`.
- Keep existing `endpoint_resolver` / `upsert` tests green.

## Note

Not demo-blocking. Independent of the defense demo; can ship whenever.
