# Qwkhnd

**Full meaning in fewer tokens.** Qwkhnd reads the files you drop
into a Source Material folder and builds a shorthand dictionary from
them: the words that save the most text get the shortest codes.
Encode any text into shorthand, decode it back exactly, and export
the dictionary.

The name and version live in one place, `qwkhnd/__init__.py` —
nothing else in the code hardcodes them.

## Install (no terminal needed)

1. Unzip the release somewhere sensible, e.g. your home folder.
2. Double-click **Install-Qwkhnd**. It makes a private Python
   environment, installs what Qwkhnd needs, and adds a menu icon.
3. Start Qwkhnd from the menu icon.

Needs Python 3.10 or newer. If `python3-venv` is missing on your
machine, the installer tells you the one command that fixes it
(`sudo apt install python3-venv`) and stops — it never runs apt
itself.

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
3. The words that save the most text get the shortest codes. Try it
   in the **Try it** window (the Try it button, or View menu), and
   export the dictionary as JSON or plain text. The **Help** menu
   opens a How to Use window, and the **Help** tab is a quick start.

On the first run, Qwkhnd drops three sample files into the Source
Material folder and shows a short Getting started checklist, so
Rebuild has something to read right away. The results appear as a
bento grid (characters saved, files read, words found, codes
assigned, before/after sample); the dictionary table has a live
search box and a Show all switch. The **View** menu holds two
presets — **Big text** and **Reduced motion** — and the shortcuts
are **Ctrl+R** rebuild, **Ctrl+E** Try it / encode, **/** search.

The **File** menu holds Open folder, the exports, the Debug
report, **Restore previous dictionary** (brings back the
dictionary from before the last rebuild), and Quit. You can also
drag files onto the window to copy them into the Source Material
folder, or drag a folder onto it to make it the source folder.
Every control explains itself when you hover over it, and the
**Help** menu lists all the keyboard shortcuts.

## What it reads

- `.txt`, `.md` and other text files (UTF-8 and UTF-16, with or
  without a byte-order mark; bad bytes tolerated)
- `.pdf` files with a text layer (via pypdf)
- `.docx` Word files, including headers, footers, footnotes and
  endnotes (standard library only)
- `.epub` ebooks, read in chapter order
- `.html` files, with the markup stripped (script and style
  dropped); `.md` links keep their text and drop their URLs
- Anything else is attempted as plain text when it looks like text

## What it skips (every skipped file is listed, with its reason)

- Images, audio and video — turning those into text needs OCR or
  speech recognition, which is not in this version
- Archives, programs and other binary files
- Old `.doc` / `.xls` / `.ppt` files — save them as `.docx` to use them
- Hidden files and folders, and scanned PDFs with no text layer
- File symlinks (never followed), and Qwkhnd's own dictionary
  and log files (the skipped list names the reason for each one).
  There is no size limit on the files Qwkhnd reads.

## How the codes work

- Words are counted across everything readable; the words that save
  the most text (how often a word appears times how many characters
  its code saves) get the shortest codes: the top word gets the
  1-letter code `a`, the next `b`, and so on, then the 2-letter
  codes, then 3-letter. A word gets no code when its code could not
  make it shorter.
- A word is replaced by `~` + its code — but only when the coded
  form is actually shorter, so encoding never makes text longer.
  A literal `~` in your text is written as `~~`.
- Decode is exact: decoding encoded text gives back the original,
  character for character. The test suite hammers on this.
- When decoding, a code is the `~` sign plus all the letters
  right after it, so put a space after a code when you write
  shorthand by hand (otherwise `~brown` is read as one code,
  not as a short code plus the rest of a word).
- Words are case-sensitive ("The" and "the" are different
  entries), and words shorter than 3 letters never get codes (they
  cannot shrink: `~` + a 1-letter code is already 2 characters).

## Troubleshooting

- **The app will not start from the menu icon.** The start-up
  error is saved to `~/Qwkhnd/logs/startup-error.txt` — open it
  to see what went wrong. The usual cause is a missing system Qt
  library: run the installer again and it names the library and
  the package that provides it.
- **The saved dictionary was damaged.** Qwkhnd starts empty and
  says so in a notice. Press **Rebuild** to make a new one from
  the folder, or use **File → Restore previous dictionary** to
  bring back the one from before the last rebuild.
- **The folder moved.** The folder field remembers the old path:
  press **Browse** to pick the new one (a warning appears beside
  the field when the folder does not exist), then press Rebuild.

## Offline, private, $0

Qwkhnd never goes on the network — it only reads files on your
machine. No accounts, no keys, no secrets anywhere in the code.
Your dictionary is saved at `~/Qwkhnd/qwkhnd-dictionary.json`;
logs live in `~/Qwkhnd/logs`. The **Debug report** button writes
a scrubbed report you can send when something goes wrong.

## For developers

- Run the tests: `python -m unittest discover -s tests`
  (engine, extraction, debug log, GUI, installer, worker-thread
  rebuild, cancel, single instance, plus the UI: checklist,
  samples, disclosure, search, bento, notices, state, presets,
  shortcuts, copy, and the v0.3 additions: EPUB, drag and drop,
  restore, tooltips, menus, perf guards).
- Build the release zip: `python3 build_zip.py`
- The debug log layer is the BNB T21 `debug_log.py` module
  (standard library only), dropped in unchanged.
- The name and version live only in `qwkhnd/__init__.py`
  (`APP_NAME` / `APP_ID` / `VERSION`); the file names, desktop
  files and installer strings carry the name too.

## License

MIT — see `LICENSE`. Copyright (c) 2026 Joshua Lofland.
