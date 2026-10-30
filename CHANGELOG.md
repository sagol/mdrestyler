# Changelog

## Unreleased

- A worked example, `examples/cross-restyle`: two public-domain passages restyled into each other's voice, with the profiles, takes, choices and measures.

## 0.1.0

First release.

- `mdrestyler` command: `scan`, `check`, `rank`, `book`, `install`, `profile validate`, `verify`, `--version`.
- The package runs from its skill folder with nothing installed, or from the wheel.
- Profiles use the `mdrestyler-author-profile/1` and `mdrestyler-copy-guard/1` schemas.
- `book` takes the reading order from a `--list` file; the own-book scan takes it from the eligibility record.
- `names.configure()` lets an embedding tool set its message names, its delegated-approval check, its book layout, and the earlier schemas and defaults it still reads.
- The agent skill includes a need-first restyle procedure for any Markdown book.
