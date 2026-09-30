---
name: measure-in-the-browser
description: Discipline for verifying visual work (layout, color, contrast, typography, hover placement, theme toggles) by measuring the rendered page instead of reading the stylesheet or judging a screenshot by eye. Use whenever a UI change is about to be reported as done, whenever a screenshot looks wrong or blank, whenever a flex or grid rule seems ignored, whenever a contrast or accessibility floor is claimed, and before a third attempt at any color solve. Derived 2026-09-15 from seventy review rounds on a web app; every rule below cost at least one pass.
metadata:
  version: 1.1.0
  source: derived from the review records of a web app and KiT (2026-09)
  owner: SPRIC76
---

# Measure in the browser

A stylesheet declaration proves the shape was authored, not that it was rendered.
Occlusion, a parent's opacity, a running transition, a wrapper element and an
8-bit alpha are all invisible to a text assertion and to the eye. Measure the
thing the reader sees, with JavaScript, and report the number.

## Before refining anything: measure what shows

Three passes were once spent on shapes that sat entirely behind a desk. Before
polishing a shape, measure how much of it is on screen (bounding rect against the
occluder's rect, or `elementFromPoint` at its centre). If most of it is hidden,
the round is about the occluder.

## How to take a reading

- **Use `getBoundingClientRect` and `getComputedStyle`, not pixels.** In the Claude
  desktop Browser pane a screenshot taken after scrolling comes back black or as a
  stale frame; zoom-to-region is unsupported. For a picture of something lower on
  the page, hide the elements above it (`style.display='none'`), shoot at scroll 0,
  then reload.
- **Settle before reading.** A theme flip or class change can start hundreds of
  transitions; a mid-transition computed value is a real value and looks like
  evidence. Run `document.getAnimations().forEach(a => a.finish())` first and
  report the count with the reading. A hidden pane may not advance animations at all.
- **Read at the reader's width.** Placement rules that depend on free margin
  (tooltips into the gutter) are invisible at the pane's natural width and at a
  1600 "desktop". Emulate 1920x1080 before calling a placement wrong. Synthetic
  hovers must wait past the open delay; the close has its own fade.
- **Measure the box the engine consults, not the element you styled.** A component
  that wraps its children makes the wrapper the flex item; `flex: 1 0 auto` on the
  child does nothing. Read `getComputedStyle` on `container.children`, then write
  the rule on the container's children.
- **A flex parent blockifies `inline-block`.** The declaration reads correct in the
  sheet and is inert on the page; in a column flex the item is also stretched.
  Signal: the element's box is far wider than a `Range` over its own contents.
  Fix: `width: fit-content` plus `align-self: center`.
- **Count lines from the text, not the box.** Box height over line-height counts
  padding and borders as lines: a one-line strip with 6.4 px padding read as two
  (KiT, 2026-09-28). Select the element's contents with a `Range` and count the
  distinct `top`s of its client rects.

## Contrast and color

- **Composite before measuring.** A ratio taken against a translucent fill is wrong
  until the fill is flattened over its real backdrop — and the backdrop is often
  theme-mapped, so one ink may face four grounds. Read ink and track out of the
  stylesheet; do not copy them into the test.
- **Alpha is stored to eight bits.** `0.903` composites at `230/255 = 0.90196`; a
  floor certified in floating point can be crossed by the pixel. Snap alphas to
  `n/255` before checking any floor that depends on one.
- **A contrast floor is a ceiling on lightness only.** Solving several stops one at
  a time against one floor lands them at the same lightness with only hue left to
  tell them apart. Solve them as one problem: maximise the smallest OKLab gap
  between neighbours subject to every stop clearing the floor, then check the
  lightness spread, not just the hue spread.
- **When ink cannot clear, make it ground.** A color light enough to look vivid is
  too light to be a letter on paper; that is arithmetic, and a fourth solve will not
  change it. Compute the boundary, say it cannot be done as text, and change the
  substrate: text becomes a chip, a dot becomes a ring, a line becomes a fill.
- **Levels are not perception.** Equal 8-bit deltas on dark and light grounds are
  not equally loud; use APCA (or another perceptual measure) when the claim is
  "the two themes carry the same texture." Contrast bounds what a layer may cost
  the text; it says nothing about what the layer *is* — a texture also has an
  internal step ratio, and that needs its own function and constant.
- **A mask wider than its box has no zero edge.** Every layer under a mask must
  start and end at transparent and carry its own falloff; compose to the mask's
  opaque core, derived from the mask string.

## Reporting

State the reading, the condition it was taken under (width, theme, settled or
not), and the floor it was checked against. When a live reading contradicts an
earlier measured claim, re-measure settled before rewriting code or telling the
operator. A before and an after are comparable only when measured the same way;
if the first number was wrong, retract it in writing beside the rule.
