# Reading the measures

## A check

`python3 scripts/mdrestyler.py check --profile <profile folder> draft.md [more.md] [--json] [--strict]`

The report names each draft's SHA-256 and the profile's revision, then gives:

- **Status** of the profile: approved, draft or default.
- **Copy guard:** runs of 8 words the draft shares with a scanned book. A hit exits 1 and blocks the draft.
- **Targets:** each measure's value against the profile's range: within, near, outside or not measured, marked weak when the draft is too short for it.
- **Voice distance**, when the profile holds a calibration: the draft's mean robust distance from the profile's sources, and the share of the sources' own chapters that lie farther from the rest. A draft farther than every source chapter is a finding. Under 1,200 words it reads less reliably.
- **Narration and dialogue apart**, when the profile holds their ranges: the author's words and the spoken words, each against its own ranges. Each also gets its own distance when the profile calibrates it and the draft holds 600 words of narration or 400 of dialogue.

**Read by the narration distance.** The pooled distance also weighs how much of a unit is dialogue, which follows composition and length more than voice, so it is a poor aim for rewording. The narration distance leaves dialogue out, so it shows best what rewording can move. In one test, on a chapter of a narration-led novel against a dialogue-led reference, a restyle moved the narration distance from 1.21 to 0.93 while the pooled distance went from 1.15 to 1.14. Before you call a change a habit, compare it with the narration ranges: a take that adds dashes to narration below the range moves toward the profile, though each dash still has to serve its sentence.

`--strict` also exits 1 when a measure is outside and not marked weak, or cannot be compared because the profile was scanned by another measure method. Any error exits 2, including an invalid profile or guard.

**A revision of one unit:** `check --profile <folder> revised.md --accepted base.md`. Text the revision keeps unchanged, in place and unambiguous counts as the base's own, not a hit. Base text it repeats more often than the base is a hit at every copy, moved or ambiguous base text is uncertain, and inserted text stays checked. The alignment stops at 20,000 words or 10 seconds; past that nothing is exempt. The report names the base's SHA-256 and is stale for another base.

## Takes

`python3 scripts/mdrestyler.py rank --profile <folder> take-1.md take-2.md take-3.md`

Each file is one take of the same unit, checked alone. Takes with a copy-guard run come last, then the order follows the narration distance, the voice distance and the number of measures outside. The order informs a reading and chooses nothing. In one test the takes lay within 0.09 of each other, and the take the measure put first was the one a blind reader put last. `rank` needs two takes or more; check a single take with `check`.

## A whole book

`python3 scripts/mdrestyler.py book BOOK --profile <folder> --list units.txt [--within p90] [--json]`

The list names the units in reading order, one path per line relative to the book; blank lines and `#` lines are skipped. A unit outside the book, missing, named twice or not Markdown stops the table: there is no other order to fall back on. Each unit gets one row: voice, narration and dialogue distances, where they fall among the source chapters, measures outside and copy-guard runs. A unit with no prose, such as a part title, is listed as not measured.

The last column reads each unit's narration distance against a threshold: the narration calibration's 90th percentile, or `--within p50`, `max` or a number. *Beyond* means the unit's narration lies farther from the profile than the sources' own chapters mostly do, so read it first. *Within* means nearer. *By reading* means too little narration to measure, or no narration calibration. The column orders a reading; it decides nothing. The JSON keeps the selector and the exact value.

## Calibration

A scan calibrates each source chapter of 1,200 words or more against the median and robust spread of all the others, on one panel of measures every source chapter has and that still vary. Each distance is capped at six spreads and averaged. It needs five such chapters, and records why when it has fewer. Narration and dialogue are calibrated the same way on their own chapters (600 and 400 words), and dialogue share is in neither panel. A profile scanned before calibration has none, and the check says so; rescan its sources to add it. The idea of reading a draft against the author's own held-out text, and of measuring style by mode, comes from AuthorStyle by Fernando Paladini (MIT); the implementation is mdrestyler's own.

## Languages and limits

- One profile per language, named by its two-letter code (`AUTHOR_PROFILE.en.md`), or its three-letter code when it has none. `--lang` takes a code such as `en`, `en-GB`, `eng` or `ru`. A scan refuses a book whose language tag is missing, names no single language, or is repeated with another. Profiles named under an older three-letter or withdrawn code still load; a folder holding one language under two names is refused until one moves to `history/`.
- English and Russian have language-specific word lists; other languages get only the language-neutral measures.
- Russian dialogue is read by measure method 2: dash-led speech and its tags by the punctuation of direct speech. Speech in «ёлочки» is measured as narration, because Russian prose sets titles, thoughts and quotations in them as often as speech. A profile from another method is compared on the other measures, with the changed ones reported as incomparable. A calibrated distance whose panel holds a changed measure is not given: rescan the profile to get it back.
- There is no word segmenter for Han, kana, Thai, Lao, Khmer or Myanmar. Text in those scripts is processed, but segmentation is reported as partial, and a guard with no hits says partial, not clear.
- A scan reads at most 64 MiB of expanded EPUB text across its books (`--max-expanded-mb`). Fixed ceilings: 256 MiB per EPUB, 10,000 entries, 16 MiB per text entry, 4,000,000 words.
- What an EPUB shows is judged from its stylesheets: `display` and `visibility` by CSS's cascade; rules the scan cannot settle are never applied, and where one could hide or show text the profile marks its styles partial and names the rule.
- The profile's files are identified by their bytes. Keep Git from converting their line endings (`<profile folder>/** -text` in `.gitattributes`).

A successful exit records a measurement. It does not establish quality, complete segmentation or originality.
