import logging
from logging.handlers import RotatingFileHandler

from VIVAANXMUSIC.security import redact_secrets

LOG_FILE = "log.txt"
LOG_LEVEL = "INFO"

FORMAT = "[%(asctime)s - %(levelname)s] - %(name)s - %(message)s"
DATEFMT = "%d-%b-%y %H:%M:%S"

logging.basicConfig(
    level=LOG_LEVEL,
    format=FORMAT,
    datefmt=DATEFMT,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=3, encoding="utf-8"),
    ],
)

for lib, level in [
    ("httpx", logging.ERROR),
    ("pyrogram", logging.ERROR),
    ("pytgcalls", logging.ERROR),
    ("pymongo", logging.ERROR),
    ("ntgcalls", logging.CRITICAL),
]:
    logging.getLogger(lib).setLevel(level)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact_secrets(str(value)) for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_secrets(str(arg)) for arg in record.args)
            else:
                record.args = (redact_secrets(str(record.args)),)
        return True


for handler in logging.getLogger().handlers:
    handler.addFilter(SecretRedactionFilter())


def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)
