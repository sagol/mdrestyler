# Cross-restyle: Huck Finn and the governess

This example restyles two well-known public-domain passages into each other's voice and measures the result with mdrestyler. It follows the skill's restyle procedure from start to finish: a profile for each voice, a decision note, a need assessment, three takes per direction, a ranking, a choice made by reading, a preservation check, and before and after tables.

## The texts

| | Book | Voice |
|---|---|---|
| Twain | *Adventures of Huckleberry Finn* (Mark Twain, 1884), Project Gutenberg #76 | A boy telling his own story in vernacular: short words, nonstandard grammar, clauses chained with *and* and semicolons, almost no -ly adverbs, deadpan. |
| James | *The Turn of the Screw* (Henry James, 1898), Project Gutenberg #209 | A governess writing years later: long suspended sentences full of qualifications, abstract and Latinate words, many -ly adverbs, analysis of every impression. |

Both books are narrated in the first person and the past tense, so a restyle can keep the viewpoint and change only the voice. Both authors died more than a century ago, so the books are in the public domain nearly everywhere. The two writers were contemporaries with famously opposite styles.

The passages:

- [passages/twain.md](passages/twain.md): the opening of chapter VII, where Huck finds a drift canoe, saws out of his father's cabin and fakes his own murder (1,402 words).
- [passages/james.md](passages/james.md): the second half of chapter III, where the governess first sees a stranger on the tower (1,297 words).

A first choice for the Twain side, the river at dawn from chapter XIX, turned out to lie beyond the 90th percentile of its own book's chapters, so it was not a fair sample of the voice. The chapter VII opening sits near the middle of the book's spread (nearer than 45% of its chapters). The James passage sits at the edge of its book's spread (1.17 against a 90th percentile of 1.17).

## Results

Narration distance from each profile. Lower is closer; *within* and *beyond* read the distance against the 90th percentile of the profile's own chapters (Twain 1.18, James 1.17).

| Text | Twain profile | James profile |
|---|---|---|
| Twain passage | **0.84** within | 1.63 beyond |
| Twain passage restyled toward James | 1.21 beyond | **0.98** within |
| James passage | 2.31 beyond | **1.17** within |
| James passage restyled toward Twain | **1.12** within | 1.33 beyond |

Each restyle crosses over: the text moves inside the target's range and out of its source's. The escape passage, restyled, lies nearer the James profile than 55% of the James book's own chapters.

What moved, in the narration:

- Toward James: commas per 1,000 words rose from 49 to 81, into the target range; -ly adverbs from 1.5 to 8.5, still below the target's 12 to 23; long sentences from 20% to 32%; the past-tense share from 0.91 to 0.99. Mean word length barely moved (3.75 to 3.79) because the events themselves are told in plain words, and a restyle may not add new matter to say in longer ones.
- Toward Twain: -ly adverbs fell from 11.6 to 2.0 per 1,000 words, dashes from 17 to 7, vocabulary variety from 0.49 to 0.45 and the median paragraph from 338 words to 87, all into or near the target ranges. Sentences stayed more evenly long than the target's (variation 0.46 against 0.68 to 1.16): the governess's qualifications had to stay, and they keep the sentences long.

[results/matrix.md](results/matrix.md) has every take against both profiles and every narration measure before and after; [results/matrix.json](results/matrix.json) has the same numbers.

## What the example shows about the tool

- **Read the narration distance.** The tower passage restyled toward Twain has a narration distance of 1.12 from the Twain profile but a pooled distance of 1.71. The pooled distance also weighs the share of dialogue, and the Twain book is a third dialogue while the passage has none. Rewording cannot change that, so the narration distance is the one to aim at.
- **The ranking is a lead; the reading chooses.** For the escape passage the reading chose the take the ranking put first. For the tower passage it chose the second: the first-ranked take kept the source's 300-word paragraphs, so the vernacular sat inside the governess's paragraph shape. [choice.md](restyle/james-to-twain/choice.md) gives the reasons.
- **Preservation limits the voice.** No take could give the escape passage the governess's interiority, and none could strip the tower passage of its qualifications, because a restyle may not add or drop meaning. The reading also caught small additions of attitude in the chosen takes ("oddly enough", "and you could tell it"), which were removed. [lock-check.md](restyle/twain-to-james/lock-check.md) records each check.
- **The copy guard sees the source.** Against its own book's guard, each source passage shares hundreds of 8-word runs, as it should. The chosen takes still share 66 and 4 runs with their source books, mostly lists and short phrases a restyle keeps, such as the supplies Huck loads into the canoe. In a real restyle the check runs with `--accepted snapshot.md`, which counts unchanged base text as the book's own. Against the target's guard, every take is clear.

## Layout

| Path | Holds |
|---|---|
| `sources.json` | the two books: Gutenberg numbers, URLs and the SHA-256 of the files scanned |
| `profiles/twain/`, `profiles/james/` | the two profiles, each scanned from its book as a reference book, with a described voice written from the scan's samples. Both are drafts: no author approved them, which a real restyle requires |
| `passages/` | the two source passages |
| `restyle/<direction>/` | `decision.md`, `assessment.md`, `before.md`, the three takes, `rank.md`, `choice.md`, `lock-check.md`, `check.md` for the chosen take, and `after.md` |
| `results/` | every text against both profiles |
| `run.py` | regenerates every report |

The takes were written by three separate agents per direction, each given only the snapshot, the target profile and its narration ranges, with the preservation rules and no measuring tool. Unchosen takes are kept here to show the choice; a real restyle deletes them once the unit is accepted.

## Run it

From this folder, with nothing installed:

```
python3 run.py            # regenerate the reports under restyle/ and results/
python3 run.py --check    # exit 1 if a committed report is stale
python3 run.py rebuild --work /some/folder/outside
```

`rebuild` downloads the two books, checks their hashes, rescans them and compares the measures and guards with the committed profiles. Project Gutenberg sometimes regenerates its files, and a regenerated file gives a slightly different profile; the script says so when the hash differs. The reports use this repository's skill; set `MDRESTYLER=mdrestyler` to use an installed command instead.

The measures locate where a text differs from a voice. Whether a take sounds like that voice, and keeps everything else, is decided by reading it.
