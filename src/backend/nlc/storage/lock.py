
import os
import sys
from pathlib import Path
from typing import Optional
from nlc.storage.paths import get_launcher_data_dir

class SingleInstanceLock:
    def __init__(self, lock_file_path: Optional[Path] = None):
        self.lock_file_path = lock_file_path or (get_launcher_data_dir() / "launcher.lock")
        self._fd = None
        self._locked = False

    def acquire(self) -> bool:
        try:
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = open(self.lock_file_path, "a+")

            if os.name == "nt":
                import msvcrt
                try:
                    self._fd.seek(0)
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                    self._locked = True
                except (OSError, IOError):
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._locked = True
                except (OSError, IOError):
                    return False

            # Write current PID
            self._fd.seek(0)
            self._fd.truncate()
            self._fd.write(f"{os.getpid()}\n")
            self._fd.flush()
            return True
        except Exception:
            return False

    def release(self):
        if not self._locked or self._fd is None:
            return

        try:
            if os.name == "nt":
                import msvcrt
                try:
                    self._fd.seek(0)
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

            self._fd.close()
            self._locked = False
        except Exception:
            pass
        finally:
            self._fd = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Another instance of Ny-Luna is already running.")
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self.release()
