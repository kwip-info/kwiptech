# Content pipeline

The serving path reads a versioned JSON snapshot included in the release. It never
waits on upstream search APIs. Refresh locally using:

```sh
python manage.py refresh_slide_catalog --settings=show.settings --per-topic=20
```

Review the catalog diff and sample imagery before deployment. Refresh is additive
by provider ID; provider failures preserve existing records. Fewer than ten accepted
records aborts replacement. New snapshots replace the old file atomically. Source
removals and changed rights need manual review; additive refresh is not a rights
revocation monitor. This initial snapshot was fetched September 13, 2026.

## Sources

- Wikimedia Commons API: https://www.mediawiki.org/wiki/Extension:CommonsMetadata
  Eighteen subject groups with multiple bounded searches. Require JPEG/PNG, usable dimensions, creator, file
  page, supported license, and no recorded restrictions. HTML metadata is stripped;
  browser rendering uses textContent, never provider HTML. Accepted licenses are
  CC0, Public domain, and CC BY 2.0/3.0/4.0. Ambiguous, NC, ND, and SA records are
  excluded by this first importer. Keep original creator, credit, title and links.
- Art Institute of Chicago: https://api.artic.edu/docs/
  Require `is_public_domain=true` and an image ID. Use its documented IIIF image
  endpoint and CC0 attribution. Art is one topic, not weighted by record volume.
- KWIP originals: 120 presentation prompts and 32 hypothetical charts. Chart values
  are explicitly invented. No invented data is presented as research, and there
  are no fabricated attributed quotations.

Images remain on provider CDNs and use object-fit:contain, without cropping or
recoloring. A four-slide lookahead warms images with a seven-second timeout;
failed images are skipped with bounded retries. Provider outages can exhaust
image-only mode, which shows a recoverable message. Image requests reveal
ordinary visitor network metadata to those providers. No tracking or cookies are
added by this app. The page and slides use the native system font; no external font requests are made.

## Attribution and output

Each image displays a linked creator/source credit and linked license. The Sources
dialog includes the original provider credit and an explicit scaling-only statement.
Downloaded JSON includes full metadata for the actually presented sequence, so
recordings can retain credits outside the frame. Source metadata is evidence from
the provider, not a guarantee of clearance. The published corpus contains 2,159 items after source-ID and near-duplicate title
filtering, including four explicitly labeled AI-generated originals. See
GENERATED_IMAGES.md for full prompts and provenance.

## Known limits

Finite catalog reshuffling can repeat content. Public APIs are queried only during
manual refresh. There is no automatic ingestion worker, semantic linking, external
AI generation, moderation service, or saved cloud session. A production expansion
should add source review, refresh scheduling, removal handling, and a larger corpus
without putting generation or rights discovery on the click path.
