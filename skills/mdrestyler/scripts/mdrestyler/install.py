#!/usr/bin/env python3
"""Install an author profile into a profile folder: AUTHOR_PROFILE.<lang>.md, author-profile.<lang>.json and, when
present, copy-guard.<lang>.json.

  mdrestyler install FOLDER [SOURCE] --lang ru [--replace]

SOURCE is a folder a scan wrote, or another profile folder; without it, the shipped default for the language. The
shipped default, unedited, is replaced freely. Anything else already installed (a draft, an approved profile, an edited
default or an incomplete profile) is replaced only with --replace, and then its files move to FOLDER/history/<time>/
first, so the earlier profile is never lost. Standard library only."""
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # an installed skill folder stays as installed: no __pycache__ beside the scripts

from .profile import DEFAULTS, classify, every_name, family, files_for, held, load, status, unsafe_destination  # noqa: F401 (status: used through this module)
from .metrics import required_lang


GUARDED = ('none', 'default', 'incomplete', 'draft', 'approved')


def state_of(voice, lang):
    """The profile installed in a voice folder: none, incomplete, default, draft or approved. A default whose files
    differ from the shipped ones has been edited, so it counts as a draft: the author's work, kept like one. A folder
    holding the language under several spellings (an untouched en default beside an older eng profile) reads as the
    most guarded of them, so the free path for a default never passes over the other."""
    voice = Path(voice)
    return max((spelling_state(voice, family(code), lang) for code in held(lang, voice) or [lang]), key=GUARDED.index)


def spelling_state(voice, names, lang):
    if not any((voice / name).exists() for name in names):
        return 'none'
    if not (voice / names[0]).is_file():
        return 'incomplete'
    prose, measures = (voice / names[0]).read_bytes(), voice / names[1]
    try:
        markdown = prose.decode('utf-8')
    except UnicodeDecodeError:
        return 'draft'
    return classify(markdown, prose, measures.read_bytes() if measures.is_file() else None, (voice / names[2]).exists(), lang, voice, names[0])


def check_source(source, lang):
    """Raise ValueError unless source is a folder holding a complete, valid profile for lang, its guard bound to its
    measures. A file is refused before anything is installed: the installer copies a folder's files."""
    if not Path(source).is_dir():
        raise ValueError(f'{source} is not a profile folder; give the folder that holds the profile files')
    load(source, lang)


def history_folder(parent):
    """A new folder under parent named for this moment, never one that exists."""
    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    folder, n = Path(parent) / stamp, 1
    while folder.exists():
        folder, n = Path(parent) / f'{stamp}-{n}', n + 1
    folder.mkdir(parents=True)
    return folder


def install(voice, source, lang, replace=False, within=None):
    """Copy the profile for lang from source into the profile folder voice, under the two-letter names where the
    language has them; returns what was installed and kept. within: the folder no link below may lead out of (default:
    the profile folder's parent)."""
    voice, source = Path(voice), Path(source)
    names, given = files_for(lang), files_for(lang, source)   # given: as the source stores them
    if source.resolve() == voice.resolve():
        raise ValueError(f'{source} is the folder being installed into; install from another profile folder')
    check_source(source, lang)
    problem = unsafe_destination(voice, every_name(lang) + ['history'], within=Path(within) if within is not None else voice.absolute().parent)   # before anything moves
    if problem:
        raise ValueError(problem)
    state = state_of(voice, lang)
    if state not in ('none', 'default') and not replace:
        present = ', '.join(n for n in every_name(lang) if (voice / n).exists())
        raise ValueError(f'the {lang} profile in {voice} is {state} ({present}); pass --replace to replace it (its files are kept under history/)')
    voice.mkdir(parents=True, exist_ok=True)
    kept = None
    if state not in ('none', 'default') or any(code != lang for code in held(lang, voice)):   # an older spelling would stay beside the new one
        kept = history_folder(voice / 'history')
        for name in every_name(lang):   # every spelling the book holds
            if (voice / name).exists():
                shutil.move(str(voice / name), str(kept / name))
    for name, stored in zip(names, given):
        if (voice / name).exists():
            (voice / name).unlink()
        if (source / stored).is_file():
            shutil.copyfile(source / stored, voice / name)
    return {'language': lang, 'installed': [n for n in names if (voice / n).is_file()], 'status': state_of(voice, lang),
            'kept': str(kept) if kept else None}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):   # a terminal that cannot show a character gets an escape, not a crash
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(prog='mdrestyler install', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder', help='the profile folder to install into')
    parser.add_argument('source', nargs='?', help='profile folder (default: the shipped default for --lang)')
    parser.add_argument('--lang', required=True, help='profile language, such as en or ru')
    parser.add_argument('--replace', action='store_true', help="replace an installed profile other than the unedited default, keeping its files under history/")
    args = parser.parse_args(argv)
    try:
        result = install(Path(args.folder), args.source or DEFAULTS, required_lang(args.lang), args.replace)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Profile not installed: {error}\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
