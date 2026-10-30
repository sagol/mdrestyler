# mdrestyler

Measure prose against an author voice profile, and restyle a Markdown book toward it.

mdrestyler builds a voice profile from DRM-free EPUBs, or from an author's own Markdown book, and then:

- checks a draft against it: the voice distance, narration and dialogue measured apart, and each measure against its range;
- runs a copy guard, so a draft that repeats a scanned book is caught;
- ranks several takes of one unit, and tables a whole book unit by unit;
- comes with an agent skill that runs a need-first restyle: assess every unit, restyle only those that need it, pilot first, choose one whole take by reading, and check that nothing but the voice changed.

The measures locate drift. A reading decides. mdrestyler never picks a take or accepts a change by the number.

It is plain Python 3.10+ with the standard library only. English and Russian have their own word lists; other languages get the language-neutral measures.

## Install

As an agent skill, copy `skills/mdrestyler/` into your agent's skills folder and run it from there with nothing installed:

```
python3 skills/mdrestyler/scripts/mdrestyler.py --help
```

As a command, install the wheel from a release:

```
pip install https://github.com/sagol/mdrestyler/releases/download/v0.1.0/mdrestyler-0.1.0-py3-none-any.whl
mdrestyler --help
```

`mdrestyler verify` checks a skill folder against its manifest, and `mdrestyler --version` prints the version, the source commit and the manifest's digest, which is what products built on mdrestyler pin.

## Use

```
mdrestyler scan --own mine.epub --reference theirs.epub --out profile --work work
mdrestyler check --profile profile chapter-01.md
mdrestyler rank --profile profile take-1.md take-2.md take-3.md
mdrestyler book my-book --profile profile --list units.txt --within p90
mdrestyler install my-book/voice profile --lang en
```

The skill's [SKILL.md](skills/mdrestyler/SKILL.md) and its references explain each step: building and approving a profile, reading the measures, drafting toward a profile, and restyling a book.

## Example

[examples/cross-restyle](examples/cross-restyle/) restyles a passage of *Huckleberry Finn* into the voice of *The Turn of the Screw* and back, with the profiles, every take, the choice and the measures before and after.

## Building on it

A tool that embeds mdrestyler can configure it once per process with `mdrestyler.names.configure(…)`: the names its messages use, who decides a delegated approval, how its books are laid out, and which earlier profile schemas and defaults it still reads. Pin a release by its manifest digest (`mdrestyler --version`).

## Reference books

A profile keeps measurements and described features of reference books, never their text, and only the author's own books may be quoted in it. The copy guard finds any passage of fifteen words or more that a draft shares with a scanned book. It guards against copying; it is not proof of originality.

## License

MIT. See [LICENSE](LICENSE). The idea of reading a draft against the author's own held-out text, and of measuring style by mode, comes from AuthorStyle by Fernando Paladini (MIT); the implementation is mdrestyler's own.
