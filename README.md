# KWIP — the infinite slideshow

A spontaneous presentation player for kwip.tech. Unseen images, original prompts,
and explicitly hypothetical charts are shuffled into independently selected layouts
and palettes. The presenter makes the connections.

## Run locally

```sh
python -m pip install -r requirements-dev.txt
DEBUG=true python manage.py runserver --settings=show.settings
```

No database, account, billing provider, AI key, or worker is needed. Runtime dependencies are Django, Gunicorn, WhiteNoise and certifi; historical test
dependencies live in requirements-legacy.txt. The replacement
runtime is `show/`; `plane/` and its tests are retained as historical marketplace
source and rollback support. Heroku uses `show.wsgi:application` in the Procfile.
The release phase only collects static files. It never migrates or deletes old data.

## Presentation

- Right arrow, Page Down, Space, or Enter: next unseen slide.
- Left arrow or Page Up: back through actual displayed history.
- M: cycle Full remix, Gentle, and Still motion. OS reduced-motion preferences take priority.
- F: fullscreen. S: source credits. Escape closes credits or browser fullscreen.
- Images preload four selections ahead. Failed sources are skipped after a timeout;
  credits contain only slides actually displayed.
- Finish opens the source log; download before starting again or refreshing.
- A session supports 5,000 slides, then requests a fresh ride to bound browser memory.

The initial catalog contains 2,158 items. “Infinite” means continuing to recombine and
reshuffle a finite catalog, not an unlimited supply of unique source material.
There is no live AI generation or automatic publishing of unreviewed content.

## Content and randomness

See [content pipeline](docs/slideshow/CONTENT.md) and
[Heroku cutover](docs/slideshow/HEROKU.md).

A browser cryptographic seed initializes a replayable PRNG. Independent weighted
kind draws (62% images, 28% prompts, 10% charts) avoid a fixed kind cadence. Topic
shuffle bags prevent the largest collection from dominating images. Content,
layouts, and palettes have their own bags, boundary repeat avoidance, and recent-ID
suppression. This is deliberately constrained randomness; no semantic connections
are planned. Twelve palettes and five visual styles can be fixed or shuffled. Six subject worlds filter imagery; image-only and prompt-only modes are supported.
Session JSON stores full slide records, including actual displayed order, layout,
palette, source metadata and seed. No replay-import UI is included yet.

## Validation

```sh
DEBUG=true python manage.py test tests_show --settings=show.settings
node --test tests_show/*.test.mjs
node --check static/show/app.js
python manage.py collectstatic --noinput --settings=show.settings
python -m pytest -q  # historical marketplace regression coverage
```

GitHub main deployment still targets the existing Heroku app. Check the cutover
runbook before merging: old worker and billing integrations require a one-time
retirement check. The cutover receipt in enterprise operations records the deployed release and database retirement.

## Motion

Ten randomized slide transitions and independently varied content entrances use a
separate seeded random stream. Direction, duration, stagger and reveal origin vary.
Animations are interruptible: rapid navigation cancels the old effects, keeps at most
one outgoing slide, and never gates the next click on animation completion. Sources
and Finish settle motion immediately. Reduced-motion preferences bypass animation;
Gentle uses a short dissolve, and Still disables it. Promo cards float subtly only
when reduced motion is not requested. Motion recipes are included in session JSON.
