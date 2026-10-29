# Author profile (en)

Status: default. mdrestyler ships this as a starting voice for contemporary literary fiction in English. It is built from no book and it is not the author's voice. Replace it with a profile built from the author's books (`mdrestyler scan`), or edit it, and have the author approve it.
Language: en. Measures and targets: `author-profile.en.json`. Copy guard: none (no books scanned).
It is not the author's voice, so it never overrides the author's choices: the brief, the book's narrator record and the author's accepted prose decide first, and this profile guides only what they leave open. An approved profile of the author's own governs every generated draft.

## Sources

None: hand-set ranges, checked against public-domain novels so they describe real prose.

## Measured targets

What generated text is measured against. A short draft gives weak evidence for any of these.

| Measure | Default | Target range |
|---|---|---|
| median sentence length, words | 10 | 6 to 15 |
| mean sentence length, words | 13 | 8.5 to 18 |
| long end of sentence length (90th percentile), words | 26 | 16 to 36 |
| share of sentences of 6 words or fewer | 0.3 | 0.15 to 0.48 |
| share of sentences of 30 words or more | 0.06 | 0.01 to 0.14 |
| variation of sentence length (sd / mean) | 0.85 | 0.65 to 1 |
| length shift between consecutive sentences (/ mean) | 0.68 | 0.5 to 0.85 |
| median paragraph length, words | 30 | 10 to 60 |
| share of one-sentence paragraphs | 0.35 | 0.15 to 0.55 |
| share of paragraphs with dialogue | 0.45 | 0.15 to 0.8 |
| share of words spoken in dialogue | 0.25 | 0.08 to 0.5 |
| share of plain speech tags (said, asked) | 0.8 | 0.55 to 1 |
| commas per 1000 words | 55 | 38 to 75 |
| semicolons per 1000 words | 1 | 0 to 3 |
| colons per 1000 words | 1 | 0 to 2.5 |
| dashes in the prose per 1000 words | 4 | 0.5 to 9 |
| ellipses per 1000 words | 0.4 | 0 to 1.5 |
| exclamation marks per 1000 words | 1.5 | 0 to 3.5 |
| question marks per 1000 words | 6 | 2 to 14 |
| parentheses per 1000 words | 0.2 | 0 to 1 |
| simile markers per 1000 words | 1 | 0.2 to 2.5 |
| emphasized words per 1000 words | 0.8 | 0 to 2.5 |
| mean word length, letters | 4.2 | 3.9 to 4.55 |
| vocabulary variety (MATTR, 500-word window) | 0.49 | 0.44 to 0.55 |
| -ly adverbs per 1000 words | 7 | 2 to 13 |
| sentences opening on a pronoun | 0.32 | 0.18 to 0.48 |
| sentences opening on a conjunction | 0.05 | 0.01 to 0.11 |
| sentences opening on an article | 0.11 | 0.04 to 0.19 |

## Narration

- Point of view and tense: set per book. This voice works in close third or first person, past tense; present tense and other modes are book decisions.
- Distance and interiority: close. Stay inside the viewpoint character's perception and report only what they can see, know or infer. Thought comes through free indirect discourse more than through tags ("She would not call him", not "She thought that she would not call him"). Italic direct thought is rare.
- How emotion is handled: shown through action, gesture and the detail the character notices. It is rarely named and never explained after it has been shown.

## Rhythm

- Sentence movement: short and medium sentences carry the narration. A long sentence comes when the character slows down to notice or remember, and it ends on its strongest word. Pressure shortens sentences and paragraphs; reflection lengthens them.
- Openings vary: no three sentences in a row on the same first word or the same subject-and-verb frame.
- Paragraphing: one beat to a paragraph. A one-line paragraph marks a turn, not every line.

## Diction

- Register and vocabulary band: neutral and contemporary. No archaism, no technical jargon unless a character owns it.
- Words and constructions: plain, concrete nouns and verbs; adjectives and adverbs only when they carry information. The exact word over the impressive one. No thesaurus variants of "said", "walked" or "looked".

## Imagery

- Images come from the viewpoint character's world: their work, place and history, not a writer's stock.
- Figurative language is rare and earned: one simile or metaphor a page at most, never stacked, never there for its own sake.
- One or two telling sensory details rather than an inventory.

## Dialogue

- How speech is set out: double quotes, a new paragraph for each speaker.
- Tags: "said" and "asked" by default, after the first phrase of the line; an action beat instead of a tag when it adds something; no adverbs on tags.
- Speech is compressed and oblique. People interrupt, deflect and answer a different question; nobody explains the plot or the theme in a speech.
- How characters are told apart: by vocabulary, rhythm and what they avoid saying, not by spelling out an accent.

## Structure

- Chapters open in scene, close to an action or a perception, not on weather or backstory. They end on a turn, an image or a quiet line, not on a summary, and not on a cliffhanger by rule.
- A scene break (a centered `* * *`) marks a change of time, place or viewpoint.
- Summary bridges scenes briefly; the moments that matter are dramatized.

## Tone and humor

- Restrained and observant. Warm without sentiment. Humor is dry and comes from character and situation; it never winks at the reader.

## Never

- Stock phrases: "a testament to", "tapestry", "in a world where", "little did she know", "her heart pounded in her chest", "a mix of X and Y", "something shifted", "the weight of", "palpable", "unspoken", eyes that sparkle with mischief.
- The not-X-but-Y frame as a reflex, rhetorical triads, one-line morals at the end of a scene, and sentences that explain what a scene meant.
- Characters who state their feelings in complete, therapeutic sentences.
- Exclamation marks in narration, ellipses for drama, more than one semicolon a page.
- A change of viewpoint inside a scene; knowledge the viewpoint cannot have.
- Text copied or echoed from any book; naming an author whose style the book follows.

## Character speech

The limits within which a character's speech may depart from the narration's voice:

- A character may differ from the narration in vocabulary, grammar, register, sentence length and verbal habits, as their card records.
- The narration keeps its own voice. It takes on a character's words only in a free indirect passage tied to that character.
- Dialogue does not carry exposition that the narration avoids, and no character speaks in the never-list's phrases unless their card makes that their habit.

## Approval

- Approved by the author on: (default; not the author's voice)
- Changes, with dates:
