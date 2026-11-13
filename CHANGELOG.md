# Changelog

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
