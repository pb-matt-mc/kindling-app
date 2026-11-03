# Orbit usability review

Orbit compared with the initial Kindling release (the swipe app it replaces). Method: both apps run side by side on a 390x844 touch viewport with mock listings, driving a real 15-listing batch with touch events. Not measured: real users, real Claude calls, real listings.

## Scorecard

| Metric | Initial Kindling | Orbit | Verdict |
|---|---|---|---|
| Effort per decision | 1 tap. 15 listings took 15 taps, about 6.6s. | 3 gestures: drag, **Place here**, **Next listing**. | Major regression, about 3x. "Letting go commits nothing" adds a confirm step to every listing. |
| Decision complexity | Binary: like or pass. | Continuous distance, 4 blended reasons (Price, Claude's guess, Wrong vibe, Right vibe) and zones. | Major regression. Geometry is a decision on every item. |
| Photo and listing visibility | Photo fills about 80% of the screen, large title and price. | Card shrinks over the field. Title truncated, photo cut off after placing. | Regression. |
| Time to first action | One big SWIPE card. | "New batch", then an empty field whose "Nothing floating right now" text overlaps the sun. | Slight regression plus a visible layout bug. |
| Learnability | A gesture everyone knows. | Axes, frost line, Sun/Inner/Mid/Outer/Belt zones, rocket, planets, comets, binary stars, 5 event types. One line of grey hint text. | Major regression. |
| Navigation | 3 targets, one thumb. | 4-tab bar plus header and rocket. Profile opens the old `/legacy` page, a different UI. | Mixed: better bar, visible seam. |
| Accessibility | Like, nope, why and undo buttons as alternatives to swiping. | Drag-only placing. No keyboard handler on the stage, almost no labels for screen readers. | Regression. |
| Feedback and recovery | Undo. | Undo, live readout, "Called it / Close / Claude missed" after placing. | Improvement, though "Claude missed" after most placements discourages. |
| Learning quality | Opaque trait web. | Measured confidence, locked predictions, local model, evidence behind events. | Clear win. |
| Visual design | Warm, Tinder-like. | Cohesive design system and fonts. | Win. |
| Weight and speed | About 356 KB including d3, 2.4s load. | About 233 KB, 1.5s load. `app.js` grew from 42 KB to 130 KB. | Win. |
| Engineering | No tests. | Math tests, e2e device matrix, migration rollback. | Big win. |

## Grade

- Engineering and learning: A-.
- Day-to-day usability of triaging a batch of listings: C-.

Orbit treats every placement as a precise, valuable signal, so it charges about 3x the effort and much more thought per item. Triage is a high-volume loop, so any metric counting taps, time or mental effort per listing goes backwards.

## Recommended changes, by payoff

1. A fast path that commits on release (a setting, a "quick place" mode, or confirmation only past the frost line). Cuts the loop from 3 steps to 1.
2. Auto-advance after Place, with Undo as a toast.
3. Like and pass buttons (or tap zones) that drop a listing at a default Inner or Outer position, for the common case where the reason doesn't matter.
4. Bigger card, photo visible while dragging, full title.
5. A keyboard and button placement path (accessibility, and it gives the fast path a home).
6. A first-run walkthrough, and move Profile into the new UI to remove the seam.
7. Fix the empty-state text overlapping the sun.
