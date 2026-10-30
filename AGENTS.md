# AGENTS.md

Guidance for AI coding agents that call mdrestyler or change this repository.

## Calling the tool

- Load the skill first: [skills/mdrestyler/SKILL.md](skills/mdrestyler/SKILL.md). It lists the commands and the rules that always hold; its references say how to build a profile, read a check, draft toward a profile and restyle a book.
- Run it with nothing installed: `python3 skills/mdrestyler/scripts/mdrestyler.py COMMAND …`, or `mdrestyler COMMAND …` after `pip install mdrestyler`. Every command has `--help`.
- Ask for JSON when you parse a result: `check`, `rank` and `book` take `--json`; `scan`, `profile validate` and `verify` always print JSON.
- Exit status of `check`: 0 measured; 1 the copy guard found a shared run, or with `--strict` a measure is outside its range; 2 an error, such as an invalid profile. A copy-guard hit blocks the draft. `rank` and `book` exit 0 once their table is printed and 2 on an error: they inform a reading, so read the copy-guard column of each row. Each command's `--help` states its own exit codes.
- The measures locate drift; a reading decides. Never choose a take, accept a change or rewrite a sentence by the number alone. Read by the narration distance: the pooled distance also weighs the share of dialogue, which rewording cannot change.
- Only the author's own books may be quoted in a profile. A reference book's text never enters a profile, a draft or a book. Delete the scan's samples file once the profile is written.
- Keep profiles, samples, takes and run records outside the manuscript.

## Changing the repository

- Python 3.10+ and the standard library only. No dependencies, at run time or in tests.
- Tests: `python3 -m unittest discover -s tests`. `tests/test_skill.py` fails if any file names another product or holds a private path; `tests/test_example.py` fails if a report in `examples/cross-restyle` is stale (regenerate with `python3 examples/cross-restyle/run.py`).
- The skill folder is pinned by its manifest. After changing anything under `skills/mdrestyler/`, run `python3 tools/manifest.py --commit <a full source commit>`; `python3 tools/manifest.py --check` fails while it is stale. `pyproject.toml` and `mdrestyler.__version__` must agree.
- A release is two pull requests: the source change with the new version, then a receipt that records the merged source commit in `_build.json` (`tools/manifest.py --commit <merged sha>`). Tag the receipt's merge commit `vX.Y.Z` and build the wheel from it with `python3 tools/build_wheel.py`.
- The site lives in `site/`; `python3 site/validate.py` checks it against the code. See [site/README.md](site/README.md).
- Keep the documented behavior and the code in step: SKILL.md, the references, `--help`, the README and the site describe the same tool.
