# Changelog

## v0.4 — 2026-11-17

All 21 tasks from the v0.3 hands-on user review, in priority
order. The review found one critical bug (a rebuild that found
no text silently wiped the working dictionary) plus 32 smaller
findings; this release fixes all 33.

- No-wipe rebuilds (T01): a rebuild that produces zero codes
  (or reads zero files) no longer touches the dictionary, the
  saved file or the previous file, and the notice says the
  dictionary is unchanged. Restore warns instead of claiming
  success when the previous dictionary is empty.
- No-result messages (T02): a 0-code rebuild now says what
  happened — an empty folder, no readable files (with the
  skipped count and a pointer to the Skipped tab), or files read
  but no word long enough to shorten — each ending "Your
  dictionary is unchanged." when one exists. Correction to the
  review's F03: the tiny-words case showed no message at all
  (the "No readable text found" wording in the review was a
  probe reading a hidden label's stale text), so the fix adds
  the message where none existed rather than rewording one.
- Tab switches keep your place (T03): switching tabs no longer
  scrolls the results area (a guarded tab widget arms a scroll
  guard before the switch; the scroll used to land inside the
  switch itself, so a restore-after-the-fact could not work).
- Honest hero numbers (T04): the hero sub now says the saving
  is measured on a 1,500-character sample, so it no longer looks
  like it contradicts the 100-character sample tile.
- One progress story (T05): the progress label keeps the
  overall "Reading file N of M" story; the in-file percentage
  goes to the status bar only, so the two never disagree.
- Live folder validation (T06): the folder warning updates on
  every change of the field (and on startup with a moved
  folder), not only when the field loses focus.
- Decode from the input box (T07): Decode reads the text you
  type or paste, so pasted shorthand can be decoded at all;
  plain text and unknown codes each get a plain explanation.
- The sample never ends mid-code (T08): the sample tile trims
  at a word boundary and never ends on a lone `~`. Found in
  verification and fixed before shipping: a joined slice could
  come in under the trim limit yet still end on a lone `~`
  (the shipped samples did exactly this), so the strip now
  applies at any length.
- Plain skip reasons (T09): a skipped file says what happened
  in plain words ("could not read the file (permission
  denied)"), with the technical detail kept in the log; empty
  files are listed as skipped, not counted as read.
- Table room, copy, sorting (T10): the table shows 8 full rows
  at default size (the progress row hides when idle, rows are
  26 px, the table is taller, and the search-hint line — which
  restated the placeholder — is gone); right-click a row to copy
  its word, code or the whole row; clicking a column header
  sorts, clicking again reverses, and the sort survives
  rebuilds and searches.
- Honest Try-it messages (T11): a longer result says so and
  names the tilde ("1 longer. A ~ in your text is written as
  ~~."), a tiny saving with words the dictionary never saw says
  what fixes it, and Try it is disabled until a dictionary
  exists.
- Readable status-bar paths (T12): exports and debug reports
  show the file name in the status bar; the full path is the
  status bar's tooltip.
- First-run polish (T13): the progress bar is hidden until a
  rebuild runs, and the checklist stays until all three steps
  are done (trying Try it is remembered across restarts).
- Drop renames named (T14): a dropped file that lands under a
  new name says so ("Added 1 file as dropped (2).txt (that name
  was taken).").
- No-match guidance (T15): a search that finds nothing says the
  word may not be in the Source Material and what fixes it.
- Whole files (T16): the Try it window encodes and decodes
  whole files — the result is saved next to the source as
  `name.qwkhnd.txt` / `name.decoded.txt`, the source untouched.
- Import a dictionary (T17): File → Import dictionary brings
  in an exported dictionary; a bad file leaves everything
  alone, and a good one rotates the current dictionary to
  previous.
- Words without codes (T18): the words that got no code get a
  link under the Codes tile and their own tab, most-used first,
  with the reason for each ("too short to shrink" / "the next
  code would not make it shorter"). The checklist moved inside
  the scroll area, above the bento, so it scrolls away instead
  of eating fixed viewport.
- Stale-dictionary hint (T19): a gold hint under the folder
  line when the dictionary came from a different folder than
  the one shown. An imported dictionary never shows it.
- True sample copy (T20): the two sample files describe the
  savings rule (not frequency), the `~a` example names a word
  that really gets `~a` (`dictionary`), and "never makes text
  longer" carries the `~~` exception. The rewritten samples
  build 184 codes from 695 words (231 different, 47 without a
  code), saving 509 of 1,500 characters (33.9%).
- Small doc fixes (T21): the text export's header says codes
  are ranked by what they save; How to Use names the Try it
  button and lists symlinks and the app's own files among the
  skips; the debug report drops its always-empty Services
  section.
- Found in verification and fixed before shipping: on the
  first run the checklist floated mid-window (220 px of dead
  space above it) because the scroll area had no stretchable
  widget left once the results were hidden — it now sits at
  the top; and the sample tile could end on half a word
  ("fox wa") when the 100-character cut landed inside one —
  the cut now drops the fragment.

## v0.3 — 2026-11-15

All 29 tasks from the v0.2 review, in priority order: hardening,
speed, and the missing pieces.

- Safe loading and saving (T01): the saved dictionary is fully
  validated before it is trusted (every malformed shape starts
  the app empty with a notice, never a crash), and every write is
  atomic, so a failed save leaves the old file untouched.
- Streaming counting (T02): words are counted as they are read,
  never held as one giant token list, so a big rebuild stays
  light on RAM (the 14 MB probe corpus adds 0 MB above baseline,
  where v0.2 added about 390 MB), and the counting itself runs
  through Counter.update, which counts in C.
- Virtual table (T03): the dictionary table is a model/view now,
  so Show all on a 200,000-entry dictionary takes seconds instead
  of a minute and hundreds of megabytes (v0.2: 63 s and 723 MB).
- Fast search (T04): the sort runs once per dictionary and the
  search waits 200 ms after the last keystroke, so typing never
  waits on a sort.
- No dead codes (T05) and saving-ranked codes (T06): a word only
  gets a code when the code can actually shrink it, and the
  shortest codes go to the words that save the most text. The
  dictionary has zero dead codes now (v0.2 had 19 on the sample
  corpus and 81 on a 500,000-word synthetic corpus). Total
  saving is essentially unchanged: on the sample corpus v0.3
  saves 1208 of 3504 characters (34.5%, v0.2: 1231, 35.1%) with
  185 codes instead of 209; on the synthetic corpus it saves
  54.4% (v0.2: 54.5%) with 915 codes instead of 1000.
- Pinned requirements (T07): PySide6-Essentials 6.12.0 and pypdf
  7.1.0, the versions the install sim verified.
- Cancellable reads (T08): text files are read in chunks and
  PDFs page by page, so Cancel stops a big file part-way through
  and progress is shown inside the file; file symlinks are never
  followed. There is no per-file size cap, by Joshua's decision:
  streaming keeps RAM flat, so the guard is Cancel plus the
  symlink skip, not a limit.
- Big text fits (T09): the results area scrolls, so the window
  minimum stays under a 768 px screen under Big text, and the
  sample tile never clips.
- The skipped list and the sample survive a restart (T10): both
  are stored in the saved dictionary and restored on load.
- Restore (T11): every rebuild keeps the previous dictionary,
  and File > Restore previous dictionary brings it back.
- EPUB support (T12): ebooks are read in chapter order, markup
  stripped.
- Markup stripped (T13): HTML files are read with the markup
  stripped (script and style dropped); Markdown links keep their
  text and drop their URLs, and code is dropped.
- Tooltips and shortcuts (T14): every control explains itself on
  hover, the Help menu lists all the keyboard shortcuts, the
  search box has a one-line explainer, and the / key can be
  turned off in the View menu.
- File menu and a real How to Use index (T15): File holds Open
  folder, the exports, the Debug report, Restore, and Quit; How
  to Use is a section list on the left with the section text on
  the right.
- Drag and drop (T16): drop files onto the window to copy them
  into the Source Material folder (a name clash gets a number),
  or drop a folder to make it the source folder.
- Try it grows up (T17): Copy result, a sample sentence that
  encodes shorter, and Clear.
- Validation where it helps (T18): the folder field warns on the
  spot when the folder does not exist, and an empty search says
  what to try next.
- Launcher and installer (T19): the menu icon calls run.sh
  directly; a failed start saves its error to
  ~/Qwkhnd/logs/startup-error.txt; the installer names the
  actual missing library (and its package) instead of guessing,
  and a pip failure gets a plain-words message.
- Icon fallback (T20): a corrupt SVG falls back to the painter
  drawing; a missing SVG is a plain error, not a traceback.
- More from Word, more encodings (T21): .docx headers, footers,
  footnotes and endnotes count; UTF-16 without a byte-order mark
  is detected; the scan never reads Qwkhnd's own dictionary or
  logs.
- The decoding rule, documented (T22): decoding matches the
  whole run of letters after ~, so the guide says to put a space
  after a code when writing shorthand by hand. The behaviour is
  unchanged, and tests pin it.
- Reproducible zip (T23): a fixed timestamp, so the same tree
  always builds the same zip; a test proves every file in the
  tree is in the manifest.
- Uninstaller (T24): uninstall.sh plus an Uninstall-Qwkhnd
  desktop file. It removes the install and asks before touching
  ~/Qwkhnd, never deleting it unasked.
- Docs and Python floor (T25): a Troubleshooting section, the
  Python 3.10 floor stated and checked, and no hardcoded test
  count in the README (it went stale in v0.2).
- Tests for the untested paths (T26): scanned and multi-page and
  encrypted PDFs, the crash handler's report, Open folder, the
  About dialog, closing mid-rebuild, codes past 3 letters, and
  the icon fallback.
- Performance guards (T27): the suite now pins counting RAM
  (tracemalloc), Show All and search on a 200,000-entry
  dictionary, and the fixed waits in the GUI tests are deadline
  loops.
- Polish (T28): a warning glyph on notices, the disabled Rebuild
  text at 5.02:1 contrast, "Dictionary saved." in the status bar
  after a rebuild, a safe debug report button, and the
  single-instance lock released on close.
- Table density (T29): Compact/Comfortable rows in the View menu,
  remembered between runs, sized from the font so Compact never
  clips under Big text.

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
