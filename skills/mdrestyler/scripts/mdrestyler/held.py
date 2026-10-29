"""Folders held open without following a link: a run reads and writes below a folder it made or checked only through
handles opened from that one. Standard library only."""
import errno
import hashlib
import os
import secrets
import stat
import sys
from pathlib import Path


class Refused(ValueError):
    """The import refuses the source or the destination; nothing was written."""


class Stopped(ValueError):
    """A decision is needed, or a check failed; nothing was published."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def open_made(fd, name, reached):
    """The folder this run has just made as name in the folder fd holds, opened with no link followed and accepted only
    as a folder made a moment ago by this process: empty, and owned as what this process makes there is owned (its
    effective user, or, on a filesystem that maps owners, the owner of a probe file made through the folder's own
    handle, which is then removed only as that file: moved aside and compared, and only while still empty). No call
    makes a folder and opens it in one step, so this is a condition on the first opening, not proof that the folder is
    the one os.mkdir made: one put at the name in between that holds anything, or is someone else's, is refused and left
    as found, while an empty folder of the same user cannot be told from it and is used. What is opened is held, and
    bound by its handle, from then on."""
    try:
        inner = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    except OSError as error:
        raise Refused(f'{reached}, which this run had just made, cannot be opened as that folder ({error.strerror}); '
                      'nothing is written to it') from None
    try:
        owner = os.fstat(inner).st_uid
        reason = 'holds something' if os.listdir(inner) else None
        if reason is None and owner != os.geteuid():   # a filesystem that maps owners: a probe shows how it owns what this process makes
            reason = 'belongs to someone else'
            probe = f'.made-{secrets.token_hex(4)}'
            try:
                made = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=inner)
            except OSError:
                made = None
            if made is not None:
                try:
                    st = os.fstat(made)
                finally:
                    os.close(made)
                try:
                    private = aside(inner, probe, (st.st_dev, st.st_ino))
                except (FolderChanged, FileNotFoundError):
                    reason = 'changed while it was checked'
                else:
                    if os.stat(private, dir_fd=inner, follow_symlinks=False).st_size:
                        reason = 'changed while it was checked'   # written into meanwhile: kept aside, not removed
                    else:
                        os.unlink(private, dir_fd=inner)
                        if st.st_uid == owner:
                            reason = None
        if reason:
            raise Refused(f'{reached} was replaced as this run made it: the folder at that name {reason}; nothing is '
                          'written to it, and it is left as found')
    except BaseException:
        os.close(inner)
        raise
    return inner


def rename_no_replace(src, dst, dir_fd=None):
    """Rename src to dst in one step that never replaces anything: Windows' own rename, which fails when anything is at
    dst, Linux renameat2 with RENAME_NOREPLACE, macOS renamex_np or renameatx_np with RENAME_EXCL; with dir_fd, both
    names are relative to that open folder. True when renamed; False when this platform or filesystem offers no such
    rename; FileExistsError when anything is at dst."""
    if os.name == 'nt':
        if dir_fd is not None:   # no folder handles here
            return False
        os.rename(src, dst)
        return True
    import ctypes
    import ctypes.util
    try:
        libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
    except OSError:
        return False
    source, target = os.fsencode(src), os.fsencode(dst)
    if sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        libc.renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        at = -100 if dir_fd is None else dir_fd   # AT_FDCWD, or the folder held
        done = libc.renameat2(at, source, at, target, 1)   # RENAME_NOREPLACE
    elif sys.platform == 'darwin' and dir_fd is None and hasattr(libc, 'renamex_np'):
        libc.renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        done = libc.renamex_np(source, target, 4)   # RENAME_EXCL
    elif sys.platform == 'darwin' and dir_fd is not None and hasattr(libc, 'renameatx_np'):
        libc.renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        done = libc.renameatx_np(dir_fd, source, dir_fd, target, 4)   # RENAME_EXCL
    else:
        return False
    if done == 0:
        return True
    code = ctypes.get_errno()
    if code in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(code, os.strerror(code), str(dst))
    if code in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        return False   # this kernel or filesystem has no such rename
    raise OSError(code, os.strerror(code), str(src))


def rmdir_same(fd, name, known):
    """Remove the empty folder at name in an open folder only as the one known (device, inode): moved aside and compared
    there (aside), then removed by rmdir. One something stays in is left where it stands; one that took the name, or
    that something was put into meanwhile, goes back to its name (put_back). True when removed."""
    try:   # a folder something stays in is not moved at all
        inner = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    except OSError:
        return False
    try:
        with os.scandir(inner) as entries:
            if any(True for _ in entries):
                return False
    finally:
        os.close(inner)
    try:
        private = aside(fd, name, known)
    except OSError:   # gone, or another: put back or left aside, never removed
        return False
    try:
        os.rmdir(private, dir_fd=fd)
        return True
    except OSError:
        put_back(fd, private, name)
        return False


BOUND_FOLDERS = (hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'O_DIRECTORY')
                 and {os.open, os.stat, os.unlink, os.rmdir, os.rename} <= os.supports_dir_fd)


def need_folder_handles(what):
    """Refuse on a platform without folder handles that refuse symbolic links (BOUND_FOLDERS false): the import binds every
    read and write below a folder to the folder it made or checked, which by path it could not, a junction or link put in
    meanwhile leading it onto an author's files."""
    if not BOUND_FOLDERS:
        raise Refused(f'this platform offers no folder handles that refuse symbolic links, so {what} could not bind what it reads '
                      'and writes to the folders it made or checked; run it where they exist, such as Linux, macOS or WSL')


def read_handle(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(fd, 1 << 20):
        chunks.append(chunk)
    return b''.join(chunks)


def at_folder(fd):
    """An opener for open(): a name in the folder an open handle holds, never followed through a link."""
    return lambda name, flags: os.open(name, flags | os.O_NOFOLLOW, 0o666, dir_fd=fd)


class FolderChanged(OSError):
    """Something below a held folder that is not what this run made, checked or first opened there."""


def aside(fd, name, known):
    """Whatever stands at name in an open folder, moved aside under a private name in one step and compared there with
    known (device, inode), so what is then replaced or removed is what was compared: the private name when it is that
    entry. Anything else is put back where it stood without replacing anything, and FolderChanged names it; where
    something took the name meanwhile, it is left aside under the private name, which the error names instead.
    FileNotFoundError when nothing stands there."""
    private = f'.{name}.{secrets.token_hex(4)}.aside'
    os.rename(name, private, src_dir_fd=fd, dst_dir_fd=fd)
    st = os.stat(private, dir_fd=fd, follow_symlinks=False)
    if (st.st_dev, st.st_ino) == known:
        return private
    if put_back(fd, private, name):
        raise FolderChanged(errno.ESTALE, 'no longer the one this run made or first opened there; it is left as found', name)
    raise FolderChanged(errno.ESTALE, f'no longer the one this run made or first opened there; it is left aside as {private}', name)


def install(fd, tmp, name):
    """The file at tmp put in place at name only where nothing stands, by a step that never replaces: a hard link, or
    where the filesystem has none a rename that cannot replace (rename_no_replace). False when something stands there;
    OSError, with everything left where it is, where neither is offered."""
    try:
        os.link(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        return True
    except FileExistsError:
        return False
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EMLINK, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise
    try:
        if rename_no_replace(tmp, name, dir_fd=fd):
            return True
    except FileExistsError:
        return False
    raise OSError(errno.ENOTSUP, 'this filesystem offers neither hard links nor a rename that cannot replace', name)


def put_back(fd, private, name):
    """Return an entry moved aside to its name, never over anything that took the name meanwhile: by a hard link, or
    for a folder or on a filesystem without them by a rename that cannot replace. False when it stays aside."""
    try:
        os.link(private, name, src_dir_fd=fd, dst_dir_fd=fd)
    except FileExistsError:
        return False
    except OSError:
        try:
            return rename_no_replace(private, name, dir_fd=fd)
        except OSError:
            return False
    os.unlink(private, dir_fd=fd)
    return True


class Held:
    """A folder this run made or checked, held open without following a link. Every read and write below it goes
    through handles opened from that one, no link followed at any step, so a folder renamed away and replaced meanwhile,
    by a link or by another folder, receives nothing; the handle stays on the folder across its publishing rename.
    Every folder and file it makes, and in a checked folder everything there when it was checked (snapshot), is
    remembered by device and inode: a later step through a remembered folder compares it, and where this run owns the
    folder (strict) anything else is refused, never written into, listed or published; remove_owned removes only what is
    remembered. Without folder handles (BOUND_FOLDERS false) it refuses to open (need_folder_handles)."""

    def __init__(self, path, known=None, strict=True, snapshot=False, fd=None):
        """known: the (device, inode) it was checked as; None takes the folder there now, as one this run just made.
        strict=False remembers a folder or file when first opened instead of refusing it (a folder the author owns).
        fd: a handle already opened on it without following a link (open_below), which it takes over."""
        self.path, self.fd, self.strict = Path(path), None, strict
        self.folders, self.files = {}, {}   # path below the folder: (device, inode) remembered
        self.digests = {}   # path below the folder: SHA-256 of the bytes this run last wrote, read or found there
        need_folder_handles('the import')
        if fd is None:
            try:
                fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            except OSError as error:
                raise Stopped(f'{self.path} cannot be opened as a folder ({error.strerror}); it is left as found') from None
        held = os.fstat(fd)
        if known is not None and (held.st_dev, held.st_ino) != known:
            os.close(fd)
            raise Stopped(f'{self.path} is no longer the folder this run made or checked; it is left as found')
        self.fd, self.known = fd, (held.st_dev, held.st_ino)
        if snapshot:
            for rel, st in self._walk():
                (self.folders if stat.S_ISDIR(st.st_mode) else self.files)[rel] = (st.st_dev, st.st_ino)
            for rel in list(self.files):   # and what each file holds, so one edited in place is never taken for it
                try:
                    self.read(rel)
                except OSError:
                    pass

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def named(self, error, parents):
        """error, its file named by its path below the folder rather than by the bare name a handle took."""
        for attr in ('filename', 'filename2'):
            name = getattr(error, attr, None)
            if isinstance(name, str) and '/' not in name:
                setattr(error, attr, str(self.path.joinpath(*parents, name)))
        return error

    def check(self, rel, st, folder, made=False):
        """Remember what this run makes; compare what it remembers; refuse anything else in a folder it owns, or remember
        it as first opened in one it does not."""
        table, ident = (self.folders if folder else self.files), (st.st_dev, st.st_ino)
        if made or (rel not in table and not self.strict):
            table[rel] = ident
        elif rel not in table:
            raise FolderChanged(errno.EEXIST, 'not made or checked by this run; nothing is written into it, and it is '
                                'left as found', str(self.path / rel))
        elif table[rel] != ident:
            raise FolderChanged(errno.ESTALE, 'no longer the one this run made or first opened there; nothing is written '
                                'into it, and it is left as found', str(self.path / rel))

    def _folder(self, parts, make=False):
        """A handle on the folder parts names below the held one, each step opened without following a link, made
        first when make, and checked; the caller closes it."""
        fd = os.dup(self.fd)
        done = []
        try:
            for part in parts:
                made = False
                if make:
                    try:
                        os.mkdir(part, dir_fd=fd)
                        made = True
                    except FileExistsError:
                        pass
                inner = (open_made(fd, part, self.path.joinpath(*done, part)) if made
                         else os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd))
                os.close(fd)
                fd = inner
                done.append(part)
                self.check('/'.join(done), os.fstat(fd), folder=True, made=made)
        except BaseException as error:
            os.close(fd)
            if isinstance(error, OSError):
                raise self.named(error, done) from None
            raise
        return fd

    def below(self, other):
        """Whether another held folder is one inside this one: the folder reached through this one's handle at the path
        between their canonical paths, as each was opened, is the folder the other holds."""
        try:
            rel = other.path.relative_to(self.path)
        except ValueError:
            return False
        if not rel.parts:
            return False
        try:
            fd = self._folder(list(rel.parts))
        except OSError:
            return False
        try:
            st = os.fstat(fd)
        finally:
            os.close(fd)
        return (st.st_dev, st.st_ino) == other.known

    def parts(self, rel):
        """rel's names below the held folder; one that would leave it ('..', '.', or an empty name) is refused."""
        names = rel.split('/')
        if any(name in ('', '.', '..') for name in names):
            raise OSError(errno.EINVAL, 'not a name below the folder', str(self.path / rel))
        return names

    def mkdir(self, rel):
        os.close(self._folder(self.parts(rel), make=True))

    def write(self, rel, data):
        """rel written whole, its folders made as needed, and remembered. Where this run owns the folder, a name it has
        not written is only added, never written over what stands there (add); a name it wrote, or found when it
        checked, is replaced only as that file: moved aside in one step and compared there (aside), then the new file,
        written whole beside it and never through a link, put in its place where nothing stands."""
        *parents, name = self.parts(rel)
        if self.strict and rel not in self.files:
            if not self.add(rel, data):
                raise FolderChanged(errno.EEXIST, 'not made or checked by this run; nothing is written over it, and it is '
                                    'left as found', str(self.path / rel))
            return
        fd = self._folder(parents, make=True)
        tmp, made = f'.{name}.{secrets.token_hex(4)}.tmp', False
        try:
            with open(tmp, 'xb', opener=at_folder(fd)) as handle:
                made = True
                handle.write(data)
                st = os.fstat(handle.fileno())
            if rel in self.files:   # the file remembered, moved aside and compared, then the new one put only where nothing stands
                old = aside(fd, name, self.files[rel])
                if not self.same_bytes(fd, old, rel):   # edited in place since this run wrote or read it: the author's, kept
                    raise FolderChanged(errno.ESTALE, 'changed since this run wrote or read it; nothing is written over it' + (
                        ', and it is left as found' if put_back(fd, old, name) else f', and it is left aside as {old}'), name)
                try:
                    placed = install(fd, tmp, name)
                except OSError as error:
                    raise OSError(error.errno, f'{error.strerror}; the version this run wrote is left aside as {old}', name) from None
                if not placed:
                    raise FolderChanged(errno.EEXIST, f'taken while it was being replaced; the version this run wrote is left '
                                        f'aside as {old}', name)
                os.unlink(old, dir_fd=fd)
            else:   # a name this run neither wrote nor found, in a folder it does not own: replaced as POSIX renames
                os.rename(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
            self.check(rel, st, folder=False, made=True)
            self.digests[rel] = sha256(data)
        except BaseException as error:
            if isinstance(error, OSError):
                raise self.named(error, parents) from None
            raise
        finally:
            if made:
                try:
                    os.unlink(tmp, dir_fd=fd)   # the temporary name: gone after a rename, a second link after a link
                except OSError:
                    pass
            os.close(fd)

    def add(self, rel, data):
        """rel written only where nothing stands, whole or not at all: beside it first, then linked into place, which
        never replaces; an exclusive copy where the filesystem has no hard links. False when something is there."""
        *parents, name = self.parts(rel)
        fd = self._folder(parents, make=True)
        tmp, made = f'.{name}.{secrets.token_hex(4)}.part', False
        try:
            with open(tmp, 'xb', opener=at_folder(fd)) as handle:
                made = True
                handle.write(data)
                st = os.fstat(handle.fileno())
            try:
                os.link(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
            except FileExistsError:
                return False
            except OSError as error:
                if error.errno not in (errno.EPERM, errno.EMLINK, errno.ENOTSUP, errno.EOPNOTSUPP):
                    raise
                created = []   # (device, inode) of the file made, from the handle that made it: removed again, as that
                # file, if writing or closing fails

                def making(path, flags):
                    handle = at_folder(fd)(path, flags)
                    try:
                        made_st = os.fstat(handle)
                    except OSError:
                        os.close(handle)
                        raise
                    created.append((made_st.st_dev, made_st.st_ino))
                    return handle
                try:
                    with open(name, 'xb', opener=making) as copy:
                        copy.write(data)
                        st = os.fstat(copy.fileno())
                except FileExistsError:
                    if not created:
                        return False
                    raise
                except BaseException:
                    if created:
                        try:
                            os.unlink(aside(fd, name, created[0]), dir_fd=fd)
                        except OSError:   # another put at the name meanwhile: put back or left aside, never removed
                            pass
                    raise
            self.check(rel, st, folder=False, made=True)
            self.digests[rel] = sha256(data)
            return True
        except OSError as error:
            raise self.named(error, parents) from None
        finally:
            if made:
                try:
                    os.unlink(tmp, dir_fd=fd)
                except OSError:
                    pass
            os.close(fd)

    def read(self, rel, take=None):
        """The bytes of the regular file rel, checked; FileNotFoundError when nothing is there, OSError for anything
        else there. take: called with the file's size before it is read, as a budget is charged; then no more than that
        size is read, from the same handle."""
        *parents, name = self.parts(rel)
        fd = self._folder(parents)
        try:
            f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=fd)
        except OSError as error:
            raise self.named(error, parents) from None
        finally:
            os.close(fd)
        try:
            st = os.fstat(f)
            if not stat.S_ISREG(st.st_mode):
                raise OSError(errno.EINVAL, 'not a regular file', str(self.path / rel))
            self.check(rel, st, folder=False)
            if take is None:
                data = read_handle(f)
            else:
                take(st.st_size)
                chunks, left = [], st.st_size
                while left > 0 and (chunk := os.read(f, min(left, 1 << 20))):
                    chunks.append(chunk)
                    left -= len(chunk)
                data = b''.join(chunks)
            self.digests[rel] = sha256(data)
            return data
        finally:
            os.close(f)

    def same_bytes(self, fd, private, rel):
        """Whether the file moved aside under private, in the open folder fd, still holds the bytes this run last wrote,
        read or found as rel; true where it never saw them, a file remembered by device and inode alone."""
        known = self.digests.get(rel)
        if known is None:
            return True
        try:
            f = os.open(private, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError:
            return False
        try:
            return sha256(read_handle(f)) == known
        finally:
            os.close(f)

    def kind(self, rel):
        """'file', 'folder', 'link' or 'other' for what stands at rel, never followed; None for nothing."""
        *parents, name = self.parts(rel)
        try:
            fd = self._folder(parents)
            try:
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except OSError as error:
                raise self.named(error, parents) from None
            finally:
                os.close(fd)
        except FileNotFoundError:
            return None
        return ('file' if stat.S_ISREG(st.st_mode) else 'folder' if stat.S_ISDIR(st.st_mode)
                else 'link' if stat.S_ISLNK(st.st_mode) else 'other')

    def unlink(self, rel):
        """Remove the file rel if one is there, moved aside and compared first (aside), never through a link."""
        *parents, name = self.parts(rel)
        try:
            fd = self._folder(parents)
        except FileNotFoundError:
            return
        try:
            if rel not in self.files:   # refused where this run owns the folder, remembered as first seen where it does not
                self.check(rel, os.stat(name, dir_fd=fd, follow_symlinks=False), folder=False)
            private = aside(fd, name, self.files[rel])
            if not self.same_bytes(fd, private, rel):   # edited in place since this run wrote or read it: the author's, kept
                raise FolderChanged(errno.ESTALE, 'changed since this run wrote or read it; it is not removed' + (
                    ', and it is left as found' if put_back(fd, private, name) else f', and it is left aside as {private}'), name)
            os.unlink(private, dir_fd=fd)
            self.files.pop(rel, None)
            self.digests.pop(rel, None)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise self.named(error, parents) from None
        finally:
            os.close(fd)

    def empty(self):
        """Whether nothing at all stands in the folder."""
        with os.scandir(self.fd) as entries:
            return next(entries, None) is None

    def _walk(self, rel=''):
        """(path below the held folder, lstat) of everything below rel, links never followed, nothing checked."""
        out = []

        def walk(fd, prefix):
            with os.scandir(fd) as entries:
                found = [(e.name, e.stat(follow_symlinks=False)) for e in entries]
            for name, st in found:
                out.append((prefix + name, st))
                if stat.S_ISDIR(st.st_mode):
                    try:
                        inner = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except OSError as error:
                        raise self.named(error, prefix.split('/')[:-1]) from None
                    try:
                        if (os.fstat(inner).st_dev, os.fstat(inner).st_ino) != (st.st_dev, st.st_ino):
                            raise FolderChanged(errno.ESTALE, 'changed while it was listed', str(self.path / (prefix + name)))
                        walk(inner, prefix + name + '/')
                    finally:
                        os.close(inner)
        start = self._folder(self.parts(rel)) if rel else os.dup(self.fd)
        try:
            walk(start, f'{rel}/' if rel else '')
        finally:
            os.close(start)
        return out

    def listing(self, rel=''):
        """(path below the held folder, kind, size) of everything below rel, in path order, links listed and never
        followed, each entry checked; kind is 'folder', 'file' or 'other'."""
        out = self._walk(rel)
        for path, st in out:
            self.check(path, st, folder=stat.S_ISDIR(st.st_mode))
        return sorted(((path, 'folder' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else 'other',
                        st.st_size) for path, st in out), key=lambda entry: entry[0].split('/'))

    def size(self, rel=''):
        return sum(size for _, kind, size in self.listing(rel) if kind == 'file')

    def copy_in(self, source, skip=('__pycache__',)):
        """A folder's files copied in, contents only and never their modes, folders made as needed, files replaced."""
        source = Path(source)
        for folder, folders, files in os.walk(source):
            folders[:] = sorted(f for f in folders if f not in skip)
            rel = Path(folder).relative_to(source).as_posix()
            if rel != '.':
                self.mkdir(rel)
            for name in sorted(f for f in files if f not in skip):
                self.write(name if rel == '.' else f'{rel}/{name}', (Path(folder) / name).read_bytes())

    def remove_owned(self):
        """Remove what this run made or checked here, each entry only as the one remembered: files first, each moved
        aside and compared there (aside), its bytes too (same_bytes), one edited in place put back; then folders from
        the deepest, each moved aside and compared too (rmdir_same), any folder something else has put things in, or
        kept, left where it stands."""
        if self.fd is None:
            return

        def at(rel):
            *parents, name = rel.split('/')
            try:
                return self._folder(parents), name
            except OSError:   # a folder on the way is not the one remembered: what is below it stays
                return None, name
        for rel in sorted(self.files, key=lambda r: -r.count('/')):
            fd, name = at(rel)
            if fd is None:
                continue
            try:
                private = aside(fd, name, self.files[rel])
                if self.same_bytes(fd, private, rel):
                    os.unlink(private, dir_fd=fd)
                else:   # edited in place since this run wrote or read it: the author's, back under its name
                    put_back(fd, private, name)
            except OSError:   # gone, or something else, put back or left aside
                pass
            finally:
                os.close(fd)
        for rel in sorted(self.folders, key=lambda r: -r.count('/')):
            fd, name = at(rel)
            if fd is None:
                continue
            try:
                rmdir_same(fd, name, self.folders[rel])
            finally:
                os.close(fd)
