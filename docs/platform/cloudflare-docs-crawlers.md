---
title: Allowing Crawlers on the Docs
description: Why AI/LLM crawlers get a 403 on kwip.tech/docs, and how to fix it with a Cloudflare WAF skip rule scoped to the docs segment while keeping the rest of the site protected.
category: Platform Operations
---

# Allowing Crawlers on the Docs

The public documentation (`/docs`, `CLAUDE.md`, `AGENTS.md`, `llms.txt`) is meant to be
read by tools and AI assistants. By default, however, AI/LLM crawlers receive a **403**
on `kwip.tech` — and that block does **not** come from Django. It is enforced at the
**Cloudflare edge**, so the request never reaches the Heroku origin.

## Confirming the source

```console
$ curl -s -o /dev/null -w "%{http_code}\n" -A "curl/8"          https://kwip.tech/docs
200
$ curl -s -o /dev/null -w "%{http_code}\n" -A "ClaudeBot/1.0"   https://kwip.tech/docs
403
$ curl -s -o /dev/null -w "%{http_code}\n" -A "GPTBot/1.2"      https://kwip.tech/docs
403
```

The 403 response carries `server: cloudflare` and a plain-text `Your request was blocked`
body — Cloudflare's signature, not the styled Django `403.html`. Generic clients
(`curl`, `python-requests`) pass; known AI-crawler user-agents (ClaudeBot, GPTBot,
Claude-User, PerplexityBot, CCBot, …) are blocked. This is Cloudflare's **"Block AI
Scrapers and Crawlers"** managed feature (and/or Bot Fight Mode / a WAF managed rule).

## The fix — a scoped WAF skip rule

Do **not** disable AI-bot blocking site-wide. Add a rule that *skips* the block only for
the documentation segment, leaving the dashboard, API, and auth protected.

### Option A — WAF custom rule (recommended)

Cloudflare Dashboard → **Security → WAF → Custom rules → Create rule**

- **Rule name:** `Allow crawlers on docs`
- **When incoming requests match** (expression editor):

  ```
  (starts_with(http.request.uri.path, "/docs")) or
  (http.request.uri.path eq "/robots.txt") or
  (http.request.uri.path eq "/llms.txt")
  ```

- **Then take action:** `Skip`
- **Skip:** check **All remaining custom rules**, and under **More components to skip**
  enable **Managed Rules**, **Bot Fight Mode**, and **Super Bot Fight Mode** (whichever
  are present on the plan). This is what lets verified AI crawlers through on docs only.
- **Place at:** top of the custom-rules list (first match wins).

### Option B — Bot Management exception (Pro/Biz/Ent with Super Bot Fight Mode)

Cloudflare → **Security → Bots**. Where "Block AI Scrapers and Crawlers" is enabled, add
a **WAF skip rule** as in Option A scoped to `/docs*` — the AI-scraper toggle itself has
no path scoping, so the skip rule is still required.

## Verify after deploying the rule

```console
$ curl -s -o /dev/null -w "%{http_code}\n" -A "ClaudeBot/1.0" https://kwip.tech/docs
200
$ curl -s -o /dev/null -w "%{http_code}\n" -A "ClaudeBot/1.0" https://kwip.tech/docs/claude.md
200
# App stays protected:
$ curl -s -o /dev/null -w "%{http_code}\n" -A "ClaudeBot/1.0" https://kwip.tech/dashboard/
403   # still blocked — correct
```

## What the application already does

The Django origin is configured to welcome crawlers once the edge lets them through, so
no further app changes are needed after the Cloudflare rule:

- **`/robots.txt`** — `Allow`s `/docs`, `/llms.txt`, and `/static/` for AI crawlers
  (GPTBot, ClaudeBot, Claude-User, PerplexityBot, CCBot, Google-Extended, …) while
  `Disallow`ing `/dashboard/`, `/admin/`, `/v1/`, `/webhooks/`, and the auth pages.
- **`/llms.txt`** — an `llmstxt.org`-style index pointing to `CLAUDE.md`, `AGENTS.md`,
  and the docs manifests.
- **Crawler-friendly headers** — docs, manifests, raw markdown, `CLAUDE.md`, and
  `AGENTS.md` responses send `X-Robots-Tag: all` and `Access-Control-Allow-Origin: *`.

> Note: `robots.txt` advertises intent but does not *enforce* access. The 403 is removed
> only by the Cloudflare skip rule above; the headers and `robots.txt` ensure crawlers are
> handled correctly once they reach the origin.
