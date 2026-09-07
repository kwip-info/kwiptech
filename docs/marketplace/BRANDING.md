# KWIP marketplace visual system — September 7, 2026

Owner: Trevor Ewert. Existing-product depth and shared brand consistency; replaces the
marketplace's unrelated green palette. This is a bounded UI finish before tomorrow's
source work; no ingestion or commercial scope expansion.

## Phase 1 — reference and decisions (complete)

Reference: kwip.info live homepage and its `kwip-info-site` source, specifically
`kwip-info/images/favicon/favicon.svg`, `apple-touch-icon.png`, `STYLEGUIDE.md` and
`style.css`. The mark and touch icon are copied unchanged into `static/market/brand`.
The style guide's old product positioning is stale; marketplace contracts own current
product behavior. This work consumes the visual identity only.

Use the brand pink #db2777 for primary actions, #be185d hover, and the guide's
#f9a8d4 for dark-background links. Light surfaces use the live site's warm #fbfaf7
and #151515 ink. Default dark mode inverts the neutral hierarchy, using charcoal
#151515 and restrained raised #1d1d1f surfaces. System type, compact four-pixel
corners and flat controls suit tables. Secondary actions use outlined neutral buttons.
Why not copy marketing layout wholesale? Dense tables need compact actions and less
hero whitespace; brand assets and colors remain shared.

## Phase 2 — implementation (complete)

Shared header, footer, favicon and appearance partials across application and policy
pages. A local preference toggles light/dark, applies before paint, and tolerates
unavailable storage. No account state or cookies are needed. Account subroutes show
active navigation. Individual screen titles improve browser history and navigation.
Accessible focus, 44px primary controls, readable disabled controls, restrained tables,
responsive forms and code blocks. No new dependencies or third-party assets.

## Phase 3 — validated and deployed

Desktop/mobile visual pass over catalog, dataset, pricing, account, agent connection,
private jobs details, sign-in, privacy and terms. Check both themes, persistence,
keyboard focus, overflow and contrast. Existing auth, metering and rights gates remain
covered by the regression suite. Deploy through main CI; rollback is the preceding
Heroku release because no schema or data changes are required.

Validation: 379 SQLite passes / 11 PostgreSQL-only skips; 390 PostgreSQL passes after
refreshing the local hashed-static manifest. CI-selected Ruff checks and both JavaScript
syntax checks pass. Browser walkthrough covered all nine marketplace/data/policy screens
at 375px and 1280px with one h1, loaded logo and no page overflow; additional 320px
terms/query and 768px jobs-detail visual checks passed. Tables scroll within their own
container. Synthetic record retrieval returned 25 rows and its 50-credit receipt.
Light mode persists across navigation/reload; keyboard skip link has a visible ring.
Primary white-on-pink contrast 4.60:1; muted text >=5.40:1; essential control borders
>=3.66:1 against their surfaces. No source fetch, real charge, or production data mutation.

Embedded sign-in uses Clerk's documented CSS appearance variables:
https://clerk.com/docs/js-frontend/guides/customizing-clerk/appearance-prop/variables
The provider-connected sign-in component receives final visual verification after deploy.

Initial deployed receipt: commit929fa82, CI34170413557, Heroku v85. Real Clerk
sign-in inherited the correct pink/charcoal colors but also inherited the large h1
style; follow-up hides the redundant provider header (the page already has its h1)
and constrains provider card width/padding. No authentication flow changes. Final
release receipt is maintained in enterprise operations/KWIP_TECH_BRANDING_2026-09-07.md.
Light-layout audit also passed all nine screens at320/768px.
