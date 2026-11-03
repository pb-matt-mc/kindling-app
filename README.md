# Orbit

A private app for hunting secondhand things on Facebook Marketplace. Listings float on screen. You drag one onto a field around a sun. **Distance is how much you like it; direction is why it fell short.** Claude guesses, you correct it, and the system gets sharper. It replaces Kindling (the swipe app); design notes are in this README.

Runs as a small self-hosted web app, meant to be reachable only over a private network.

## Placing

- The field has a sun in the middle. Closer is better. Past the **frost line** (the dashed ring) is a pass.
- Position is a continuous blend of four reasons: **Price** (up), **Claude's guess** (down), **Wrong vibe** (left), **Right vibe** (right). Right vibe means the feel works but the item isn't quite it. A spot between two reasons splits between them; the readout shows the percentages.
- **Letting go commits nothing.** The listing rests on the field until you drag it again, tap **Back to listing**, or tap **Place here**.
- Claude's guess of what you'll dislike is always the label at the bottom. After you place, you see how close Claude's predicted rating was ("Called it", "Close", "Claude missed").
- **Undo** works after placing. Moving a placed listing later updates your taste but never re-scores Claude.
- Listings at the same spot stay separately visible (fanned out; their stored positions are never changed). A crowded Sun folds into a count you can open.

## The rocket

Bottom right of the Place screen. Drag a listing onto it: it blasts off and a drawer of your **planets** opens to its left, ending in **New planet**. Release on a planet, or release on the rocket and tap one. Dismiss the drawer and the listing returns to the field. A rocketed listing takes the planet's position, teaches taste a quarter as much, and never scores Claude. Your rocket use is shown on the System screen.

## Systems, planets, suns

- A **hunt is a solar system**; the **Galaxy** lists them. **New system** asks which listings follow the new sun and starts a new hunt with its own search terms. **Found it** closes a hunt; it stays in the galaxy as finished (reopen any time).
- **Planets** are groups you name. Listings on them are moons.
- **Binary star:** one hunt, two tastes. The active sun keeps the full field and all four reasons; the other sits nestled at the screen edge. Claude picks the starting sun; dragging a listing onto the other sun switches fields and scores that guess. Two suns is the most a screen holds.
- Before every batch, **Sun and Inner listings are re-checked**; sold ones fade but stay, with what they taught.

## What the scores mean

- **Confidence** (per system): how close Claude's predicted rating was to yours, from predictions locked *before* each listing was shown and checked against your first placement. It says **Still learning** until at least 5 checked predictions give an interval narrower than ±15 points. Rocketed listings and later moves never count. No model ever reports its own confidence.
- **Wild card rate**: how often you place toward Claude's guess (the down axis). Separate from Confidence; it never feeds it.
- **Sun pick** (binary stars): how often Claude's starting sun matched where you left the listing.

## Learning and events

Ranking and event timing come from a **local model trained on your placements** (`app/model.py`), not an LLM. Claude extracts what is in a listing, explains patterns and writes questions. When the evidence is strong, Claude **proposes** an event and you confirm or reject it; each shows the numbers behind it:

| Event | Fires when |
|---|---|
| Black hole | the Sun holds two groups of listings that rarely share a trait (12+ listings, stable split) |
| New star | 6+ listings across 2+ batches that you rate well above what the model predicts without having seen them |
| Dwarf planet | a planet with no new moon for 4 batches while you pass on listings like its moons |
| Asteroid shower | the Belt is over 30; listings the model could have explained are forgotten first, the ones it can't explain stay |
| Outlier | a placement the (otherwise reliable) model badly missed |

Events never interrupt a batch: they queue until the batch is placed, then appear one at a time. A rejected event is muted for a week and returns only if its evidence grows by half. After two rejections in the last three of a kind, that kind needs half again as much evidence. What forgotten listings taught is kept as a lesson.

## Comets

Exploration picks (formerly wildcards), controlled by the **comet rate** when you start a batch. They keep their slot whatever they score, and the recap shows how you placed them.

## Batch rules

In **New batch**, extras are rules for that batch only: `-used` (word can't appear), `!leather` (the item can't be leather; Claude judges), `$750` (under), `+$100` (over). Anything else is a soft nudge. Rules are enforced on search results and again after the closer look.

## Checklist

Your hunt's checklist (Profile) is answered yes/no/unsure by Claude for every listing. Mark an item **Must have** and a "no" removes the listing; any other "no" lowers its predicted rating.

## How a batch is built

Claude writes search terms; every term gets its share of the 45 screening slots; thumbnails are screened; about 1.5x the batch size gets a closer look; the blended prediction (Claude's look plus the local model) decides who is shown, with comets keeping their slots. Only listings you were shown are remembered as seen (listings judged not a fit are skipped for 30 days). Reposts of the same item are collapsed.

## Recap, profile, export, Obsidian

- **Recap** opens when a batch is placed: where everything landed, Claude's guess ghosted beside each, Called it / Close / Missed, comets, and the Confidence change.
- **Profile** (settings, people, spending, vibe hunts) is the classic page at `/legacy`, linked from the nav.
- **Export** keeps the original columns and adds Orbit, Reasons, Planet, Claude's predicted rating, Gap and Status.
- **Obsidian** (admin only): a note per finished batch (where each listing landed and how close Claude got), a standing note per system with scores, planets and a dated line for every event.

## Accounts and budgets

No passwords: one-time invite codes (8 characters, 7 days), then the device stays signed in for a year. Each standard account gets a weekly Claude budget (default $3, resets Monday). When it runs out, new batches lock; placing, rockets, undo and local learning keep working. Admin: `python -m app.cli admin-code`, `invite --cap 3`, `users`.

## Running it

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # ORBIT_SOURCE=mock runs everything with fake listings and no spend
.venv/bin/uvicorn app.main:app --host <BIND_ADDRESS> --port 8010
```

`deploy/orbit.service` is a systemd template that runs at low priority with a memory ceiling. Bind it to a private address, never `0.0.0.0`. Settings are `ORBIT_*`; the old `KINDLING_*` names still work.

## Safety and data

- `python -m app.cli backup | verify | restore --yes` (verified, safe while running). Migrations refuse to run without a fresh verified backup.
- `python -m app.cli migrate-orbit [--apply]` copies swipes, keepers and groups into placements and planets (old swipes keep their rating, marked "no known reason"; keepers become Sun listings); `unmigrate-orbit` removes exactly that. Old tables are never modified.
- The client makes no outside requests (fonts are served by the app; a strict Content-Security-Policy enforces it).

## Tests

```
.venv/bin/python -m pytest                      # unit, API, migration, math (JS is checked against Python)
.venv/bin/python -m pytest -m e2e tests/e2e     # real browsers: mouse and touch, desktop, S26, S26 Ultra, small iPhone, keyboard open
ORBIT_FULL_MATRIX=1 ...                         # every device and variant
```

## Layout

`app/orbit.py` placing, undo, rocket, planets, systems, binary stars, recap · `app/orbit_math.py` the field math (mirrored in `static/orbit-math.js`) · `app/scores.py` measured scores · `app/model.py`, `app/events.py`, `app/lessons.py` the local model, events and forgetting · `app/pipeline.py` batch builder · `app/recheck.py` Sun re-check · `app/backup.py`, `app/migrate_orbit.py`, `app/maintenance.py` data safety · `static/orbit.js` and `static/orbit/` the app · `static/legacy.html` + `app.js` the classic settings screens.
