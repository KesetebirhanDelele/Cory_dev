# scripts/email_ingest_daemon.py

import asyncio
import os
import sys
import logging
from datetime import datetime

from dotenv import load_dotenv

# ---------------------------------------------------------------------
#  Bootstrap: sys.path + .env
# ---------------------------------------------------------------------

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Load .env before importing anything from app.*
load_dotenv()

from app.channels.providers.mail_reader import poll_once  # noqa: E402

# ---------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
#  Main poll loop
# ---------------------------------------------------------------------

async def main() -> None:
    """
    Simple IMAP polling daemon.

    - Every IMAP_POLL_SECONDS (default 30s):
        * logs a tick
        * calls poll_once() to ingest any new emails
    """
    poll_seconds = int(os.environ.get("IMAP_POLL_SECONDS", "30"))

    logger.info("Starting email ingest daemon (poll interval=%ss)", poll_seconds)

    while True:
        logger.info("IMAP poll tick %s", datetime.utcnow().isoformat())
        try:
            await poll_once()
        except Exception as e:
            logger.exception("IMAP poll failed: %s", e)
        await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
