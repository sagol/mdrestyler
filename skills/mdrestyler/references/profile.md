# Profiles

## Files

A profile folder holds one profile per language:

| File | Holds |
|---|---|
| `AUTHOR_PROFILE.<lang>.md` | the described voice and a table of the measured targets; its status: default, draft, or approved |
| `author-profile.<lang>.json` | the measures, target ranges, function-word fingerprint, calibration and narration and dialogue ranges, with each source's hash |
| `copy-guard.<lang>.json` | winnowed hashes of the scanned books' 8-word runs, no text. The measures record this file's SHA-256 (`copy_guard_sha256`), so a guard from other books, or an edited one, is refused |
| `history/<time>/` | earlier profiles, kept when one is replaced |

The three files' hashes together are the profile's revision; every report names them. A report is stale for any other revision.

mdrestyler ships a default for English and for Russian (`scripts/mdrestyler/defaults/`): a starting voice for contemporary literary prose, built from no book. It is recognized by its exact bytes. An edited default, or one with a guard, reads as a draft.

## Build a profile from books

1. Collect DRM-free EPUBs: the author's own books (`--own`), books by other writers the author chooses (`--reference`), or both. An encrypted book is refused; never remove DRM.
2. Scan into a profile folder, with the samples in a separate work folder:
   `python3 scripts/mdrestyler.py scan --own mine.epub --reference theirs.epub --out <profile folder> --work <work folder>`
   It builds one profile per language with enough text and reports any language it skipped. An `--out` that already holds a profile is replaced only with `--replace`, which moves the old files to `history/` first. Keep both folders outside any manuscript.
3. Write the described voice in `AUTHOR_PROFILE.<lang>.md`, following [describing the voice](#describing-the-voice). Quote only books marked own, and briefly. Never paste a sample passage into the profile.
4. Delete the samples file. Show the profile to the author and record the corrections.
5. When the author approves it, write the date on the one approval field under `## Approval` (or `## Утверждение`): `- Approved by the author on: 2026-10-03` (`- Утверждён автором: 3 октября 2026 г.`). Any common spelling of one real date works: numbers in any order, or a month name in English, Russian, Ukrainian or a common European language. A placeholder, partial date or note leaves it a draft; keep notes under Changes. Only that one field approves: code, hidden text, history and a second field cannot. The check quotes a field it could not read as a date.
6. Install it: `python3 scripts/mdrestyler.py install <target folder> <profile folder> --lang <lang>`. A draft can be installed before approval and stays a draft. A draft or approved profile already there is replaced only with `--replace`, and its files move to `history/` first.

**Delegated approval.** A product that keeps decisions for the author may let a field read `Approved under delegation: <decision ID>`, such as `DEC-07`. Only that product can say whether the decision approves the profile, so mdrestyler treats such a field as a draft unless the product has configured its check (`mdrestyler.names.configure(approver=…)`). Reports name a delegated approval as delegated, never as the author's.

### Describing the voice

The scan writes measurements and an unfinished description. Its sample categories are leads, not verdicts: short sentences can be calm, and a long paragraph can be continued speech. Read each passage in its scene before using it. Publisher copy and navigation are not prose.

Describe what the voice does, not only what it avoids. Compare quiet narration, argument, an intimate exchange and pressure where the sources have them. Note how thought moves and corrects itself, how sentence shapes change with the scene, how replies evade or turn a relationship, and what makes humor, restraint or warmth particular. Keep observation, inference and the author's wishes apart, and mark each point. For a translated reference, describe the translation's wording; it is not the original author's language.

Test broad claims against a contrasting passage. A pooled sentence length mixes speech and narration, so it does not show that reflection is clipped. Sparse imagery does not ban description. Put a source's rarities under variation, not under "never".

### The author's own Markdown book

An author's own book in Markdown can be scanned once the author has confirmed which units and passages are their original prose. Write that confirmation as an eligibility file:

```json
{"decision": "Author's confirmation, 2026-10-01",
 "language": "en",
 "title": "The book's title",
 "order": ["01-first.md", "02-second.md"],
 "units": {"01-first.md": {"eligible": true, "sha256": "<the unit's SHA-256 at confirmation>", "exclude": ["a passage that is not theirs"]},
           "02-second.md": {"eligible": false}}}
```

Then scan with `--own-book BOOK --eligibility FILE`. Only eligible units are measured and sampled, without their excluded passages. Every unit in `order`, notes included, feeds the copy guard. A unit whose bytes changed since its confirmation, an exclusion that matches nothing, or a unit named twice stops the scan. The book is read through a held folder handle, with no link followed.

## Reference books

- A profile keeps measurements and described features of reference books, never their text.
- The copy guard keeps the smallest hash in every eight consecutive 8-word runs of each book. It checks every run of the draft's words three ways: as a reader sees them; with markup removed but hidden words kept; and as raw text. Any passage of fifteen space-delimited words or more that a draft shares with a scanned book is found when it runs unbroken in one of the three; a shorter one only when one of its hashes was kept. It guards against copying, not concealment, and it is not proof of originality.
- A text never names a reference author or says it imitates one. Which books shaped a profile is recorded in the profile alone.
- A profile in a public repository is public, source list included.

## Changes

A change to an approved profile is the author's decision, recorded under its Approval and Changes. It stales every check and review made against the old revision, and so does a rebuilt guard. A new scan gives a new draft profile; it replaces the installed one only through `install`.
