# Changelog

## v0.2 — 2026-11-13

Full UI redesign, from the audit against the BNB UI Design Source
File Library (13 findings, 13 tasks, all built).

- First run that works (T1): three real sample files about what
  Qwkhnd does are added to an empty Source Material folder on the
  first run only (a settings flag means deleted samples never
  re-appear), plus a dismissible 3-step Getting started checklist
  that never returns after the first rebuild.
- A real identity (T2): dark navy surfaces from the icon palette
  (#14202e), gold accent (#f2c14e), light blue secondary (#7fd4ff);
  the window icon is now set on every window (v0.1 never did).
- Progressive disclosure (T3): the first screen shows only the
  folder picker, Rebuild, and the checklist; stats, table, exports
  and Debug report appear after the first successful rebuild (or
  at once when a saved dictionary exists). Try it moved out of the
  tabs into its own window (geometry remembered, opened from the
  button and the View menu). Nothing was removed, only reorganised.
  Note: the project rule in design-rules.md still says "Try it tab"
  — that wording change is flagged to the library thread, which owns
  the rules; it is not edited here.
- Searchable dictionary (T4): live search over the whole
  dictionary, and a Show all / Top 100 switch (top 100 stays the
  default view).
- Bento stats (T6): a 4-column bento grid with a hero tile
  (characters saved, percentage big), files read, words found,
  codes assigned, and a sample tile that explains itself.
- Inline notices (T5): folder-missing, empty-rebuild, export-failure
  and rebuild-failure messages now appear in the window (dismissible,
  with what to do next) instead of only in the status bar.
- Skipped files surfaced (T9): the Skipped tab is badged with its
  count when skips exist, and the files tile links to it.
- State preserved (T7): the active tab, the selected word, and the
  scroll position all survive a rebuild.
- Help split (T8): the Help tab is now a quick start; the How to
  Use window keeps the full index. No sentence appears in both.
- Feedback moments (T10): the Rebuild button dips on press and the
  codes count ticks up when a rebuild finishes (both under 300 ms,
  nothing loops or runs at rest).
- View menu presets (T11): Big text and Reduced motion, remembered
  between runs. Reduced motion keeps every state change and drops
  the animation.
- Keyboard path (T12): Ctrl+R rebuild, Ctrl+E Try it / encode,
  / focuses table search; 2 px gold focus ring, Tab in visual order.
- Copy polish (T13): the round-trip mismatch message names the
  saved debug report path; the folder hint says what the folder is
  for; the sample tile has its explainer.
- Layout fixes found in verification (all measured with probes,
  not eyeballed): the first 3-row bento left the dictionary table
  one row tall at the default size, and its minimum heights summed
  to 580 px in 466 px of space, so the sample tile and the table
  both clipped. The bento is now 2 rows (hero 2 wide, sample
  half-width beside the codes tile), the default window is
  1100x720, the table has a 140 px minimum, the sample shows its
  first 100 characters (60 under Big text, where 100 would clip —
  the caption always says which), and the count label shares the
  search row. The first-run screen also spread its widgets out
  (a hidden widget's stretch is ignored, so the spare space split
  evenly between them) — a bottom spacer takes it now, so the
  first screen packs tight and the empty space pools at the
  bottom. Two copy fixes from the final verification pass: the
  search count now says "1 match" for a single result (it said
  "1 matches"), and the How to Use window says "the folder in
  the main window" instead of "the folder above" (it is a
  separate window now, so "above" pointed at nothing).

## v0.1 — 2026-11-13

First version, released under the real name Qwkhnd (built under
the working names "Shorthand" and "Qkhnd", renamed on the day).

- Native PySide6 window: Source Material folder picker (default
  `~/Qwkhnd/Source Material`, created on first run), Rebuild
  button, stats, dictionary table, skipped-files list, Try it tab,
  Help tab, Help menu with a How to Use window.
- Rebuild runs on a worker thread: the window never blocks, with
  progress (files done / total), Cancel, and an activity light in
  the status bar. Cancelling keeps the old dictionary.
- Single instance: starting Qwkhnd again raises the window that is
  already open. Window size is remembered between runs.
- Text extraction from `.txt`, `.md`, `.pdf` (pypdf), `.docx`
  (standard library), plus other text files attempted as plain text.
  Every skipped file is listed with its reason — nothing is silently
  ignored.
- Qwkhnd engine: frequency-ranked codes (shortest codes to the
  most frequent words), encode, exact round-trip decode, export as
  JSON and readable text, before/after sample with character savings.
- Rebuild from scratch on demand; dictionary auto-saved and reloaded
  on the next start.
- Debug log layer (BNB T21): rotating timestamped logs, last-200
  ring buffer, traceback capture, scrubbed report on demand.
- GUI double-click installer (`Install-Qwkhnd`), icon (SVG + PNGs),
  menu entry, `qwkhnd` launcher. No terminal in any path.

Not in v0.1: images/audio/video (need OCR/speech), old `.doc` files,
case-folded codes, markerless codes. See the README for the full list.
