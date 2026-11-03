"""Logging: everything goes to the systemd journal (stderr) and to data/orbit.log (rotated)."""
import logging
from logging.handlers import RotatingFileHandler

from . import config

LOG_PATH = config.DATA_DIR / "orbit.log"

log = logging.getLogger("orbit")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    log.propagate = False


def recent(n=60, min_level="WARNING"):
    """Last n log lines at or above min_level, newest first."""
    levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    floor = levels.get(min_level, 30)
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    out, block = [], []
    # keep multi-line entries (tracebacks, reply snippets) attached to their header line
    for line in lines:
        parts = line.split(" ", 3)
        if len(parts) >= 3 and parts[2] in levels and line[:4].isdigit():
            if block:
                out.append(block)
            block = [line]
        elif block:
            block.append(line)
    if block:
        out.append(block)
    keep = [b for b in out if levels.get(b[0].split(" ", 3)[2], 0) >= floor]
    return ["\n".join(b) for b in reversed(keep[-n:])]
