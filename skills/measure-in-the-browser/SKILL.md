---
name: measure-in-the-browser
description: Discipline for verifying visual work (layout, color, contrast, typography, hover placement, theme toggles, and a page's first load frame by frame) by measuring the rendered page instead of reading the stylesheet or judging a screenshot by eye. Use whenever a UI change is about to be reported as done, whenever a screenshot looks wrong or blank, whenever a flex or grid rule seems ignored, whenever a contrast or accessibility floor is claimed, before a third attempt at any color solve, and to play-test any change to what a page's load paints (a flash, a stand-in, a font swap, an empty slot on a first visit). Derived 2026-09-15 from seventy review rounds on a web app; every rule below cost at least one pass.
metadata:
  version: 1.2.1
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
occluder's rect, or `elementFromPoint` at its center). If most of it is hidden,
the round is about the occluder.

## How to take a reading

- **Use `getBoundingClientRect` and `getComputedStyle`, not pixels.** In some agents' built-in browser panes a screenshot taken after scrolling
  comes back black or as a
  stale frame; zoom-to-region is unsupported. For a picture of something lower on
  the page, hide the elements above it (`style.display='none'`), shoot at scroll 0,
  then reload. A load under test is the exception: its frames are the evidence
  (First frames, below).
- **Settle before reading.** A theme flip or class change can start hundreds of
  transitions; a mid-transition computed value is a real value and looks like
  evidence. Run `document.getAnimations().forEach(a => a.finish())` first and
  report the count with the reading. A hidden pane may not advance animations at all.
  When the load itself is under test, do not settle: settling hides the very frames
  in question (First frames, below).
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

## First frames: play-test the load

A settled page proves where the load ends, not the way there. A cold first visit
shows whatever paints before the scripts, fonts, textures and shaders arrive: a
stand-in, a fallback font, an empty slot, two layers crossing. A reading taken
after load never sees any of it (a site's landing page, 2026-09-30: a flat placeholder
sphere sat in the hero for 2.4 s of every first visit while every settled check
passed). Play-test every iteration that touches what a load paints.

- **Film every painted frame of a cold load.** A fresh browser profile per run
  (empty cache, shaders never compiled); Chrome's screencast
  (`Page.startScreencast`) from before the first paint to a second after the last
  layer arrives; each frame read beside the page's own state at that moment,
  logged every animation frame by a script that runs before the page's own
  (`Page.addScriptToEvaluateOnNewDocument`). Screenshots on a timer miss the
  frames that matter.
- **Write the failure as a rule on the frames, then prove it red on what is
  live.** Name what must never show (a stand-in before the real thing, anything
  painted over it once it draws, an ornament before the words, a last frame that
  is not the finished page) and run the rule on production's build first: a
  check that production passes has not seen the defect.
- **Stress the load, not only the page.** Every width the page answers to (375,
  768, 1440, 1920); unthrottled, Fast 4G, Slow 4G, 4x and 6x CPU, and a slow
  network with a slow CPU; reduced motion; fonts held back; the feature missing
  (no WebGL, no script, a lost context); a resize mid-load; a tab opened in the
  background; reloads in quick succession; a repeat visit.
- **Prove each condition can fail.** A background tab was once filmed as the
  whole window with the page in a corner, and a detector reading at the page's
  scale passed it; production must fail in every condition the check claims.
- **Compare a substitute with the real render by number.** A poster or fallback
  image is measured against the scene's own render at the same size (mean
  gray-level difference, with the bar stated), not approved by eye.
- **Look at the frames yourself.** Here the pixels are the evidence, read by
  number and by eye; the DOM says what was meant to paint. Keep a filmstrip (a
  cell every 100-200 ms, its times listed) and the first, failing and last
  frames; open them and say what a visitor sees at each time beside the
  numbers. A font that swaps a second in, or half a phone screen left empty, is
  a finding even when every rule passes.

Report each run's width and condition, when the words and the real first frame
painted, and pass or fail for the change and for production.

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
  tell them apart. Solve them as one problem: maximize the smallest OKLab gap
  between neighbors subject to every stop clearing the floor, then check the
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
