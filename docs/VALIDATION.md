# Validation

## What the tests cover

`python3 -m unittest discover -s tests` runs, with the standard library only:

- `test_voice.py`: reading EPUBs (spine order, front matter, notes, encodings, DRM refused, stylesheets deciding what shows), scanning, the measures, calibration and narration and dialogue apart, the copy guard in its three readings, `--accepted` for a revision, ranking, the book table and its restyle reading, installing with history, approval fields, languages and limits. The books are synthetic EPUBs the tests build.
- `test_core.py`: the configured approval, layout, schemas and defaults, the shipped defaults, the unit list, the standalone own-book eligibility, and the command's version, verify and validate, run from a copy of the skill folder with `python3 -S` and a decoy package in the working directory.
- `test_action.py`: the GitHub Action's script runs the command it is given, splits its arguments like a shell, and passes the exit status through.
- `test_example.py`: the cross-restyle example's committed reports are what `examples/cross-restyle/run.py` produces from its profiles and texts.
- `test_site.py`: the website's version, command examples, links, JSON, JSON-LD and public files agree with the code (`site/validate.py`).
- `test_skill.py`: the skill's references keep the rules the restyle depends on, and no file in the repository names another product. These are static checks of the text: they say a rule is written, not that an agent follows it.

`python3 tools/manifest.py --check` fails when the manifest is stale. `python3 tools/build_wheel.py` builds the wheel from the skill's own files and fails if it holds anything the command does not need.

## Known limits

- On Python 3.10 and 3.11, a few full-precision values in `--json` output (such as the fingerprint cosine) can differ in their last digit between runs, because summation order follows string hash order. Python 3.12 and later give the same bytes every run, and so does `PYTHONHASHSEED=0` on older versions. Printed tables round far above that digit.
- Script detection follows the running Python's Unicode data: Python 3.10 has Unicode 13, so text in a script added later, such as Kana Extended-B (Unicode 14), is not reported as needing a segmenter there.
- Hosted CI may not run for this repository; local runs on Python 3.10 and 3.14 are the record.
- The measures locate drift for a reader. They do not establish literary quality, and the copy guard is not proof of originality.
