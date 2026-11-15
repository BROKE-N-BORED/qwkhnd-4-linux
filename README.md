# Qwkhnd

**Full meaning in fewer tokens.** Qwkhnd reads the files you drop
into a Source Material folder and builds a shorthand dictionary from
them: the most frequent words get the shortest codes. Encode any text
into shorthand, decode it back exactly, and export the dictionary.

The name and version live in one place, `qwkhnd/__init__.py` —
nothing else in the code hardcodes them.

## Install (no terminal needed)

1. Unzip the release somewhere sensible, e.g. your home folder.
2. Double-click **Install-Qwkhnd**. It makes a private Python
   environment, installs what Qwkhnd needs, and adds a menu icon.
3. Start Qwkhnd from the menu icon.

If `python3-venv` is missing on your machine, the installer tells you
the one command that fixes it (`sudo apt install python3-venv`) and
stops — it never runs apt itself.

Terminal path, if you ever want it: `bash install.sh`, then
`bash run.sh` (or the `qwkhnd` command after installing).

## Use

1. Drop files into the Source Material folder
   (`~/Qwkhnd/Source Material` by default — use Browse to point
   somewhere else, or Open folder to jump straight to it).
2. Press **Rebuild dictionary**. Qwkhnd reads every file it can
   and builds a new dictionary from scratch. The rebuild runs in
   the background, so the window stays usable: progress shows
   under the button, and **Cancel** stops it (the old dictionary
   stays in place until a rebuild finishes).
3. The most frequent words get the shortest codes. Try it in the
   **Try it** window (the Try it button, or View menu), and export
   the dictionary as JSON or plain text. The **Help** menu opens a
   How to Use window, and the **Help** tab is a quick start.

On the first run, Qwkhnd drops three sample files into the Source
Material folder and shows a short Getting started checklist, so
Rebuild has something to read right away. The results appear as a
bento grid (characters saved, files read, words found, codes
assigned, before/after sample); the dictionary table has a live
search box and a Show all switch. The **View** menu holds two
presets — **Big text** and **Reduced motion** — and the shortcuts
are **Ctrl+R** rebuild, **Ctrl+E** Try it / encode, **/** search.

## What it reads

- `.txt`, `.md` and other text files (UTF-8; bad bytes tolerated)
- `.pdf` files with a text layer (via pypdf)
- `.docx` Word files (standard library only)
- Anything else is attempted as plain text when it looks like text

## What it skips (every skipped file is listed, with its reason)

- Images, audio and video — turning those into text needs OCR or
  speech recognition, which is not in this version
- Archives, programs and other binary files
- Old `.doc` / `.xls` / `.ppt` files — save them as `.docx` to use them
- Hidden files and folders, and scanned PDFs with no text layer

## How the codes work

- Words are counted across everything readable; the most frequent
  word gets the 1-letter code `a`, the next `b`, and so on, then the
  2-letter codes, then 3-letter.
- A word is replaced by `~` + its code — but only when the coded
  form is actually shorter, so encoding never makes text longer.
  A literal `~` in your text is written as `~~`.
- Decode is exact: decoding encoded text gives back the original,
  character for character. The test suite hammers on this.
- Words are case-sensitive ("The" and "the" are different
  entries), and words shorter than 3 letters never get codes (they
  cannot shrink: `~` + a 1-letter code is already 2 characters).

## Offline, private, $0

Qwkhnd never goes on the network — it only reads files on your
machine. No accounts, no keys, no secrets anywhere in the code.
Your dictionary is saved at `~/Qwkhnd/qwkhnd-dictionary.json`;
logs live in `~/Qwkhnd/logs`. The **Debug report** button writes
a scrubbed report you can send when something goes wrong.

## For developers

- Run the tests: `python -m unittest discover -s tests`
  (150 tests in v0.2: engine, extraction, debug log, GUI,
  installer, worker-thread rebuild, cancel, single instance,
  plus the v0.2 UI: checklist, samples, disclosure, search,
  bento, notices, state, presets, shortcuts, copy).
- Build the release zip: `python3 build_zip.py`
- The debug log layer is the BNB T21 `debug_log.py` module
  (standard library only), dropped in unchanged.
- The name and version live only in `qwkhnd/__init__.py`
  (`APP_NAME` / `APP_ID` / `VERSION`); the file names, desktop
  files and installer strings carry the name too.

## License

MIT — see `LICENSE`. Copyright (c) 2026 Joshua Lofland.
