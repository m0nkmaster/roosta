"""Bounded raw Markdown editing in the visible workspace."""
from contextlib import ExitStack, contextmanager
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import sys

from roosta.workspace import MAX_DOCUMENT_BYTES, visible_path


LIBC = ctypes.CDLL(None, use_errno=True) if os.name == "posix" else None


class EditError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def conflict():
    return EditError(409, "The document changed or was removed. Copy your draft, then reopen the document.")


@contextmanager
def parent_directory(root, path):
    # Never follow a link between validation and use. Pin the parent for staging and rename.
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    with ExitStack() as stack:
        parent = os.open(root.anchor, flags)
        stack.callback(os.close, parent)
        for part in (*root.parts[1:], *path.parts[:-1]):
            parent = os.open(part, flags, dir_fd=parent)
            stack.callback(os.close, parent)
        yield parent


@contextmanager
def snapshot(parent, name):
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    if not stat.S_ISREG(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
        raise EditError(403, "Editing requires a regular file with no symbolic links.")
    with os.fdopen(os.open(name, flags, dir_fd=parent), "rb") as source:
        info = os.fstat(source.fileno())
        mode = stat.S_IMODE(info.st_mode)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or mode & 0o7000:
            raise EditError(403, "Only regular, single-link Markdown files can be edited.")
        if not mode & 0o222 or not os.access(".", os.W_OK, dir_fd=parent):
            raise PermissionError
        data = source.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            raise EditError(413, "The editor supports documents up to 2 MB.")
        identity = (info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns)
        revision = hashlib.sha256(repr(identity).encode() + data).hexdigest()
        live = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not os.path.samestat(info, live) or info.st_ctime_ns != live.st_ctime_ns:
            raise conflict()
        yield data, revision, info, source.fileno()


def preserve_permissions(source, fd, info):
    new = os.fstat(fd)
    if (new.st_uid, new.st_gid) != (info.st_uid, info.st_gid):
        os.fchown(fd, info.st_uid, info.st_gid)
    os.fchmod(fd, stat.S_IMODE(info.st_mode))
    if sys.platform == "darwin":
        # macOS ACLs are separate from mode bits and extended attributes.
        if LIBC.fcopyfile(source, fd, None, 1 | 4):  # COPYFILE_ACL | COPYFILE_XATTR
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    elif hasattr(os, "listxattr"):
        attrs = os.listxattr(source)
        for key in set(os.listxattr(fd)) - set(attrs):
            os.removexattr(fd, key)
        for key in attrs:
            value = os.getxattr(source, key)
            if key not in os.listxattr(fd) or os.getxattr(fd, key) != value:
                os.setxattr(fd, key, value)


def exchange(parent, first, second):
    # Both kernels use flag 2 for atomic exchange. Both names must still exist.
    rename = getattr(LIBC, "renameatx_np" if sys.platform == "darwin" else "renameat2", None)
    if rename is None:
        raise EditError(403, "This platform does not support atomic document exchange.")
    if rename(parent, os.fsencode(first), parent, os.fsencode(second), 2):
        code = ctypes.get_errno()
        if code in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP):
            raise EditError(403, "This filesystem does not support atomic document exchange.")
        raise OSError(code, os.strerror(code))


def matches(parent, name, fd, info, data):
    live = os.stat(name, dir_fd=parent, follow_symlinks=False)
    return (os.path.samestat(live, info) and live.st_nlink == 1 and live.st_mode == info.st_mode
            and live.st_uid == info.st_uid and live.st_gid == info.st_gid and live.st_mtime_ns == info.st_mtime_ns
            and live.st_size == len(data) and os.pread(fd, len(data) + 1, 0) == data)


def replace_document(root, path, parent, source, info, original, content):
    temporary = ".roosta-edit-" + secrets.token_hex(16)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600, dir_fd=parent)
    cleanup = True
    try:
        with os.fdopen(fd, "wb") as staged:
            staged.write(content)
            staged.flush()
            preserve_permissions(source, fd, info)
            os.fsync(fd)
            candidate = os.fstat(fd)
            with parent_directory(root, path) as live:
                current = os.stat(path.name, dir_fd=live, follow_symlinks=False)
                if (not os.path.samestat(os.fstat(live), os.fstat(parent))
                        or not os.path.samestat(current, info) or current.st_ctime_ns != info.st_ctime_ns):
                    raise conflict()
            exchange(parent, temporary, path.name)
            # The former target is now at temporary. Never unlink it until verified.
            cleanup = False
            try:
                with parent_directory(root, path) as live:
                    if (os.path.samestat(os.fstat(parent), os.fstat(live))
                            and matches(parent, temporary, source, info, original)
                            and matches(parent, path.name, fd, candidate, content)):
                        cleanup = True
                        return
            finally:
                if not cleanup:
                    try:
                        if matches(parent, path.name, fd, candidate, content):
                            exchange(parent, temporary, path.name)
                            cleanup = matches(parent, temporary, fd, candidate, content)
                    finally:
                        if not cleanup:
                            raise EditError(409, f"Another writer interrupted recovery. Copy your draft and "
                                                f"inspect {path.parent / temporary} beside the document.")
            raise conflict()
    finally:
        if cleanup:
            os.unlink(temporary, dir_fd=parent)


def edit_document(root: Path, raw: str, revision=None, content=None):
    if not isinstance(raw, str) or not raw or len(raw) > 500 or "\\" in raw or "\0" in raw or not visible_path(Path(raw)):
        raise EditError(400, "Only visible workspace Markdown documents can be edited.")
    if os.name != "posix":
        raise EditError(403, "Secure document editing is unavailable on this platform.")
    import fcntl

    path = Path(raw)
    saving = content is not None
    if saving and not re.fullmatch(r'[a-f0-9]{64}', revision or ''):
        raise EditError(400, "Reopen the document to obtain a valid revision.")
    if saving and len(content) > MAX_DOCUMENT_BYTES:
        raise EditError(413, "The editor supports documents up to 2 MB.")
    try:
        if saving:
            content.decode("utf-8")
        with parent_directory(root, path) as parent:
            if saving:
                fcntl.flock(parent, fcntl.LOCK_EX)
            with snapshot(parent, path.name) as (original, current, info, source):
                if not saving:
                    return {"content": original.decode("utf-8"), "revision": current}
                if current != revision:
                    raise conflict()
                replace_document(root, path, parent, source, info, original, content)
                return {"saved": True}
    except FileNotFoundError as exc:
        if saving:
            raise conflict() from exc
        raise EditError(404, "The document no longer exists.") from exc
    except UnicodeError as exc:
        raise EditError(415, "Only UTF-8 Markdown can be edited.") from exc
    except PermissionError as exc:
        raise EditError(403, "Check write permissions on the document and its folder.") from exc
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EISDIR, errno.ENXIO):
            raise EditError(403, "Editing requires a regular document with no symbolic links in its path.") from exc
        raise EditError(503, "Check available space and access to the workspace, then retry.") from exc
