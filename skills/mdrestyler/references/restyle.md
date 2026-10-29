# Restyle a book

A restyle rewrites chosen units of a book toward a profile, keeping everything but the voice. It spends its takes only where the voice really differs, and nothing replaces accepted text before the user accepts it. A product built on mdrestyler may add its own decision classes, locks, review stages and records. Where it does, its rules apply on top of this procedure, and none of the steps below is skipped.

Keep every record outside the manuscript, in a run folder the user names, such as `restyle/<run>/`, with one folder per unit.

## 1. Decision note

Write it before any take, and have the person who owns the book confirm it:

- the profile, approved, with its three hashes (the profile revision a report names);
- the scope: the units, each with the SHA-256 of its accepted text;
- the threshold that orders the assessment (`p90` unless the note names another);
- the pilot unit, or the rule that picks it from the assessment, such as "the first unit in reading order that needs a restyle";
- the user's preserve list and ending constraints, if any;
- who accepts the pilot and who accepts the run.

A change to any of these is a new decision note. Units assessed under the old note are stale.

## 2. Before table

```
python3 scripts/mdrestyler.py book BOOK --profile <folder> --list units.txt --within p90 > restyle/<run>/before.md
python3 scripts/mdrestyler.py book BOOK --profile <folder> --list units.txt --within p90 --json > restyle/<run>/before.json
```

## 3. Need assessment

Read every unit in scope against the profile's described voice and its narration measures, beyond-threshold units first. Record each one as either:

- **needs a restyle**, naming the difference the description grounds; or
- **no restyle needed**, with its distances, the reason, and the SHA-256 of the bytes you read.

Either result can fall anywhere on the table: a unit beyond the threshold may need nothing, and one within it may need work. Note what locked text, such as quoted documents or records, adds to a distance, and never reword it to lower one. Keep anything the user asks for directly, regardless of the assessment, as its own recorded direction.

If no unit needs a restyle, the run ends with the assessment and its report: no takes, no pilot, no promotion.

## 4. Pilot

Draw the pilot from the units that need a restyle. If the named pilot needs none, the decision's owner names another, recorded; never swap it silently. Restyle the pilot as in step 5 and show it. Go on to other units only after the pilot is accepted. A rejected pilot changes the profile or the decision note, never the preservation rules in step 6.

## 5. Each unit

1. Save the accepted text as `snapshot.md`, apart from every candidate.
2. Write three takes (or the number the note sets), each from the same reading, in fresh contexts where you can.
3. With several takes, `rank` them; with one, `check` it.
4. Read every take against the snapshot and the profile, and choose one whole take. Write why in `choice.md`. Never splice takes.
5. Check the chosen take as step 6 and step 7 say, and fix inside the take anything they find.
6. Keep the takes you did not choose until the unit is accepted or sent back, then delete them. Generated takes never become reference evidence or profile sources.

## 6. Preservation

A restyle changes only the voice: wording, sentence shape and length, paragraphing, rhythm, imagery, and narrative distance within the viewpoint. Check the chosen take against the snapshot, side by side, for:

- events and their order;
- facts, numbers, dates, names and quoted documents, at every occurrence;
- each dialogue line's speaker, act and meaning, in the same order;
- in fiction, what each character knows and when, and the order of reveals;
- in factual prose, every negation, attribution, qualification and cited claim;
- chapter and scene boundaries;
- the user's preserve list and ending constraints.

A meaning change with unchanged numbers is a failure. Write the result to `lock-check.md`.

## 7. Bounded checks

- `check --profile <folder> <chosen> --accepted snapshot.md`: the copy guard and the measures, read on what a restyle can move (the narration distance and the narration's measures). The pooled distance is reported, not targeted.
- A prose check on every rewritten sentence: idiom, sentence meaning, invented detail, explanation the reader already holds, and patterns typical of generated text.
- A seam check at both joins with the neighboring units.

A guard that cannot run (missing, damaged or of another algorithm) is the state **guard unavailable**, and that unit cannot be promoted.

## 8. Promotion

Read the candidate back, diff it against the snapshot, record the acceptance, and only then replace the accepted text. Promotion never happens without the recorded acceptance.

## 9. Resume

Classify each unit in this order:

1. **unknown:** required evidence (the decision note, the assessment, the snapshot, or the candidate a record names) is missing or unreadable;
2. **stale:** the decision note changed since the unit's assessment, or a no-restyle unit's bytes differ from its assessed hash. Reassess it before any take;
3. **done:** a current no-restyle assessment, and the unit's bytes still equal its assessed hash. Done is terminal;
4. **promoted:** the text equals its accepted candidate (checked before snapshot equality);
5. **pending:** a current needs-restyle assessment, and the text equals its snapshot. Only pending units continue to takes;
6. **conflict:** anything else. Report it, and change nothing.

In a mixed run, an unchanged no-restyle unit stays done while a needs-restyle unit resumes.

## 10. After table

Run the before commands again into `after.md` and `after.json`, with the same `--within`, and keep them beside the before table. The tables locate change; the user's reading accepts it.
