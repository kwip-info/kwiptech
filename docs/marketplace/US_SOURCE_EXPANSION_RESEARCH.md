# US jobs source expansion evidence — September 8, 2026

Owner: KWIP Technology. Scope: free US-first job sources beyond the existing
Himalayas evaluation and the separately selected NYC Open Data `kpav-sd4t` source.
This review changes no collection permissions. No job payloads were ingested,
accounts created, suppliers contacted, or schedules activated.

The useful outcome is a repeatable source pipeline with honest freshness and reuse
conditions, not a larger count of nominal integrations. NYC remains the strongest
immediate addition found. The six candidates below are a research queue, **not six
cleared sources**. A government domain, accessible API, or open-source client does
not establish that every employer-authored description can be commercially resold.

## Priority and disposition

| Priority | Source | Why it matters | Current disposition |
| --- | --- | --- | --- |
| 1 | DOL OFLC H-2A/H-2B disclosure files | Actual historical US employer/job-opportunity facts, wages and program dates; quarterly bulk releases | Next historical-data investigation; administrative determinations must not masquerade as currently open ads |
| 2 | Montgomery County MCG Open Positions | Public-domain municipal vacancy IDs and dates, compatible Socrata adapter | Freshness hold: official metadata last changed July 8, 2024 |
| 3 | USAJOBS Search / Historic JOAs | Broad federal coverage and an explicitly historical endpoint | Policy hold: robots disallows all API-host paths; standalone feed/resale prohibited |
| 4 | DOL SeasonalJobs | Agricultural and non-agricultural seasonal opportunities across the US | Supported bulk route and description reuse unresolved; no archive scraping |
| 5 | Remotive | Free remote jobs with dates, description and eligibility fields | Does not fit current gated marketplace; API path robots-disallowed |
| 6 | NSF vacancies | Small first-party federal recruitment feed candidate | Catalog feed link is now a blocked HTML listing; no supported feed verified |

## 1. DOL OFLC disclosure files

[Official performance data](https://www.dol.gov/agencies/eta/foreign-labor/performance)
offers quarterly cumulative and annual historical files plus per-release record
layouts. FY2026 Q3 covers determinations through June 30, 2026, announced August 14.
H-2A/H-2B are more relevant to job opportunities than treating every PERM/LCA case as
a live vacancy. Later releases can revise determinations. [Release announcement](https://www.dol.gov/agencies/eta/foreign-labor).

[DOL copyright policy](https://www.dol.gov/general/aboutdol/copyright) permits reuse
of public-domain federal material with no implied endorsement, but distinguishes
third-party copyrighted text. Begin a future evaluation with structured facts and
source attribution; do not assume attached employer narratives have the same rights.
Do not collect recruiter contact lists, housing details or worker information merely
because adjacent files exist.

The [robots file](https://www.dol.gov/robots.txt) returned HTTP 200; the performance
page and published file directories are not listed as disallowed. A direct web-tool
open of the performance page returned 403; official indexed documentation was
available. No attempt to evade that response or download workbook payloads occurred.
No numeric download quota was located. Proposed cadence: monthly metadata review,
one download per new quarterly file, conditional requests and checksum receipts,
with immediate stop/backoff on 403/429/503.

Next step: verify the current supported download from the hosted runtime, inspect
only the official record layouts, and design a separate record kind such as
`labor_certification_opportunity`. Preserve program/case identity, determination
status, employment dates and dataset release date separately. Do not set
`published_at` from a case decision date or imply that a certification proves an
available job. This is promising historical enrichment; it is not a drop-in live
job-board adapter.

## 2. Montgomery County MCG Open Positions

[Dataset](https://data.montgomerycountymd.gov/d/vds6-zrjk),
[metadata API](https://data.montgomerycountymd.gov/api/views/vds6-zrjk.json).
A single metadata-only request returned `licenseId=PUBLIC_DOMAIN` and
`rowsUpdatedAt=1720447212` (July 8, 2024). Fields: `vacancynumber`, `department`,
`jobtitle`, `numberofopenings`, `startdate`, `enddate`, `employmentcategory`,
`recruitmenttype`, `professionalarea`. No salary, description or application URL
column was advertised. The claimed update frequency is weekly; the timestamp does
not support calling this a current feed. No rows were requested.

[Portal FAQ](https://data.montgomerycountymd.gov/stories/s/Open-Data-Guide-FAQ/6kvv-e4m6/)
supports reuse and republication, subject to the
[terms](https://data.montgomerycountymd.gov/terms-of-use). Those terms require their
specified attribution/disclaimer, prohibit implied endorsement and unapproved county
symbols, and reserve withdrawal rights. A short generic credit alone is insufficient;
prepare the prescribed notice before any display.

[Robots](https://data.montgomerycountymd.gov/robots.txt) returned 200 with a one-second
crawl delay, query-navigation restrictions and OData exclusions. The metadata/SODA
resource route is not listed as disallowed. Follow
[Socrata throttling guidance](https://dev.socrata.com/docs/app-tokens.html): public
queries are possible, app tokens raise limits, and 429 means throttle. Proposed
future budget: one bounded request weekly, not daily, after freshness is resolved.

Next step: weekly metadata-only recheck. Enroll only if data updates resume or if an
explicitly labeled historical snapshot is desired. Do not manufacture descriptions
or row-specific application links absent from the source schema.

## 3. USAJOBS

[API reference](https://developer.usajobs.gov/api-reference/) supports Search,
Historic JOAs and Announcement Text. Search needs a requested API key, with up to
500 records per page and 10,000 per query under the
[limits guide](https://developer.usajobs.gov/guides/rate-limiting).
[Historic JOAs](https://developer.usajobs.gov/api-reference/get-api-historicjoa)
requires no authentication, provides current/past structured announcements and
continuation tokens, and includes agency, appointment, salary interval, eligibility
and related metadata. Technical availability is strong.

The [registration terms](https://developer.usajobs.gov/apirequest/index) explicitly
allow internal normalization/deduplication with accurate display, credit and links
back, but prohibit third-party standalone data feeds/resale and competing data
products. This is a material conflict with KWIP's eventual metered API/export model.
[API-host robots](https://data.usajobs.gov/robots.txt) returned 200 with wildcard
`Disallow: /`. No API records were fetched.

Next step: keep disabled. A future explicit provider clarification would need to
cover the robots/API conflict and intended distribution model. Registration or
normalization alone would not solve either. No supplier outreach is authorized by
this research record.

## 4. DOL SeasonalJobs

[SeasonalJobs](https://seasonaljobs.dol.gov/) is the obvious first-party current
companion to OFLC historical disclosures. It can add non-tech, on-site US coverage.
The [robots file](https://seasonaljobs.dol.gov/robots.txt) returned 200, allows `/`
and disallows `/archive/`. Do not exploit slash/query matching differences to crawl
an archive. No current documented public bulk API or numeric rate quota was verified
in this review; unofficial descriptions of website internals are not an integration
contract.

The DOL public-domain/third-party distinction above also applies here. Employer job
orders can contain narratives and personal contact information; their presence on a
public government site is not blanket clearance for a commercial text feed.

Next step: identify an official export or syndication interface and its field-level
reuse terms before implementing. Prefer the published OFLC bulk files for historical
facts in the meantime. Do not reverse-engineer private/internal endpoints or crawl
every job detail page as a substitute for a supported data interface.

## 5. Remotive

The [publisher's API documentation](https://github.com/remotive-com/remote-jobs-api)
documents a free active-job JSON feed with IDs, publication date, company, optional
salary/type, geographic eligibility and HTML description. It recommends at most
four requests daily and blocks excessive requests above twice per minute. Data is
delayed 24 hours. Attribution and original Remotive links are required; third-party
job-site submission and collecting signups/emails to show listings are prohibited.
Those restrictions conflict with using it as another gated KWIP sample or downstream
metered feed. [Robots](https://remotive.com/robots.txt) additionally disallows
`/api/*`. No API data was fetched.

Next step: disabled. Do not adapt the API just because its JSON shape is convenient.
Provider-specific permission would be necessary for this product, and paid API
negotiation is outside the free-source scope.

## 6. NSF vacancies

[Official Data.gov catalog entry](https://catalog.data.gov/dataset/nsf-vacancies-all-positions)
describes an all-positions RSS feed, but its resource points to the current openings
HTML page rather than an actual feed. The catalog's license field points to the NSF
homepage, not a specific reuse license. Its `P1W` modified value is a cadence-like
string, not evidence of a recent data refresh.

The [current route](https://www.nsf.gov/careers/openings) presented a bot verification
page. [Robots](https://www.nsf.gov/robots.txt) returned 200 and explicitly disallows
that openings route and its query variants. Stop there; do not automate the challenge.

Next step: retain only as a discovery lead until NSF publishes a supported feed with
current policy. Its small federal scope also overlaps USAJOBS; it should not consume
engineering time ahead of NYC and the DOL historical investigation.

## Repeatable review checklist

For every candidate, record owner, exact endpoint, stable identity fields, license
and attribution URLs, robots URL/result, review and next-review dates, upstream
freshness, proposed budget, and independent display/export/history permissions.
Policy review never silently enrolls a source. Additive schema changes should keep
unknown dates and eligibility unknown, preserve source-native values, and avoid
inferring job closure from absence in a bounded sample.

Review this queue September 15, 2026. Focus the next review on restoring one useful
candidate or discovering one well-licensed first-party feed, not cycling through
unlicensed mirrors. Salary tables, occupational classifications, job counts and
visa determinations are useful context but must not inflate the count of current
job postings. Keep them explicitly typed when the product chooses to include them.
