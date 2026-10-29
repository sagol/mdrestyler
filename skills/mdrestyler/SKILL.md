---
name: mdrestyler
description: Measure prose against an author voice profile and restyle a Markdown book toward it. Builds a profile from DRM-free EPUBs or the author's own Markdown book, checks drafts (voice distance, narration and dialogue apart, copy guard), ranks takes of one unit, tables a whole book, and runs a need-first restyle with a pilot, whole-take choice and preservation checks. Standard library Python only. Use for building or installing a voice profile, checking a draft's voice or copying, choosing between takes, or restyling chapters or a book.
---

# mdrestyler

mdrestyler measures a text against an author voice profile and helps move a book toward one. The measures locate drift; a reading decides. Never pick a take, accept a change or rewrite a sentence by the number alone.

Run every command from this skill folder with nothing installed: `python3 scripts/mdrestyler.py COMMAND …`. With the package installed from its wheel, `mdrestyler COMMAND …` is the same command. `--help` on each command says more.

| Command | Does |
|---|---|
| `scan` | builds a profile, one per language, from `--own` and `--reference` EPUBs or `--own-book BOOK --eligibility FILE` |
| `check` | measures drafts against `--profile FOLDER` and runs the copy guard; `--accepted BASE` for a revision of one unit; exit 1 on a shared run |
| `rank` | orders two or more takes of one unit |
| `book` | checks every unit a `--list` file names, one row each, with a restyle reading against `--within` |
| `install` | installs a profile into a profile folder, keeping the earlier one under `history/` |
| `profile validate` | reports a profile folder's status, or why it is not valid |
| `verify` | checks this skill folder against its manifest; `--expect DIGEST` checks the digest too |

## Read before you act

- Building a profile, describing the voice, approval and installing: [references/profile.md](references/profile.md).
- What the check reports and how to read it, languages and limits: [references/measures.md](references/measures.md).
- Drafting toward a profile, one take or three: [references/drafting.md](references/drafting.md).
- Restyling chapters or a whole book: [references/restyle.md](references/restyle.md). Read it all before the first take.
- Reference books and copying: [references/profile.md#reference-books](references/profile.md#reference-books).

## Rules that always hold

- A profile describes a voice; it never outranks the brief, the narrator's record or accepted text where they decide. A conflict with an approved profile goes to the author.
- Only the author's own books may be quoted in a profile. A reference book's text never enters a profile, a draft or a book.
- Candidate text never changes a profile, and generated text is never evidence of the author's voice.
- A copy-guard hit blocks a candidate. If the check cannot run, the candidate stays unfinished: reading never stands in for the guard.
- A product built on mdrestyler (a book tool, an editorial collection) may add its own records, locks and approvals. Where it does, its rules apply on top of these.
