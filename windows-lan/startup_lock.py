"""Serialize recovery/startup; a dead launcher cannot leave a locked file."""
import msvcrt


class StartupLock:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        if not path.stat().st_size:
            self.file.write(b'\0')
            self.file.flush()
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError('Classroom startup is already in progress. Wait for its window.') from None

    def release(self):
        if self.file is not None:
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()
