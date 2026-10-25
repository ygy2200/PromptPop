"""调试日志：开关控制 + 轮转文件 + 脱敏（便于真机问题上报）。"""
import logging
import re
from logging.handlers import RotatingFileHandler

from .config import config_dir
from .util import mask_secret

_LOGGER_NAME = "promptpop"
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|[A-Za-z0-9_\-]{32,})")


class _MaskFilter(logging.Filter):
    def filter(self, record):
        try:
            record.msg = _SECRET_RE.sub(lambda m: mask_secret(m.group(1)),
                                        str(record.msg))
        except Exception:
            pass
        return True


def _log_path():
    return config_dir() / "promptpop.log"


def configure(enabled):
    logger = logging.getLogger(_LOGGER_NAME)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    if not enabled:
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)
        return
    try:
        p = _log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(p), maxBytes=1_000_000, backupCount=3,
                                 encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        fh.addFilter(_MaskFilter())
        logger.addHandler(fh)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.info("debug log enabled")
    except Exception:
        logger.addHandler(logging.NullHandler())


def get_logger():
    return logging.getLogger(_LOGGER_NAME)
