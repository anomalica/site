# Analytics: Umami (self-hosted, cookieless)

The site uses **Umami**, Mark's self-hosted instance, reached through a first-party
front door so no request leaves Anomalica's own domain:

- Endpoint: `https://analytics.anomalica.is` (Bunny reverse-proxy pull zone on
  Anomalica infra, forwarding to the shared Umami instance; same data/dashboard).
- Website id (public): `75a7c240-1ce0-4348-973f-400c2b022987`.
- Dashboard: the Umami instance (Mark's login).

## How it's wired

A small inline snippet in `layouts/_default/baseof.html` POSTs a pageview to
`/api/send` (no external script, no cookies, no PII). It's gated `{{ if hugo.IsProduction }}`
so the dev server never pollutes stats. Pattern ported from `kuracms/kura/src/lib/umami.ts`.
Per-visitor opt-out: `localStorage.umami.disabled = "1"`.

Privacy disclosure: `content/legal/privacy` (Analytics section).

## Gotcha when smoke-testing

Umami silently drops requests its bot filter flags, returning `{"beep":"boop"}` with
HTTP 200. A bare curl User-Agent (e.g. `Mozilla/5.0`) trips it; real browsers don't.
So smoke-test with a full browser UA (or a real browser), else it looks broken when
it isn't.

## Strict CSP (if ever added)

No CSP today. If one is added: `connect-src https://analytics.anomalica.is`.
