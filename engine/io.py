"""Crash-safe local artifact writes."""
import json
import os
import stat
import tempfile


def atomic_write_text(path, text, encoding="utf-8"):
    """Replace ``path`` atomically after flushing the complete new content to disk."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    prior_mode = None
    try:
        prior_mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if prior_mode is not None:
            os.chmod(tmp, prior_mode)
        os.replace(tmp, path)
        # Persist the directory entry as well as the file contents when the platform allows it.
        directory_fd = None
        try:
            directory_fd = os.open(directory, os.O_RDONLY)
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path, value):
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
