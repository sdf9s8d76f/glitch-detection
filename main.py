import asyncio
import logging

from config import SERVICES
from parsing import parse_rpt_logfile

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


async def run_parsing_loop() -> None:
    while True:
        try:
            for service in SERVICES:
                await parse_rpt_logfile(
                    service["id"],
                    service["access_token"],
                    service["webhook_url"],
                )

        except Exception as error:
            logger.exception(
                "Unhandled Exception when running function `parse_rpt_logfile`.",
                exc_info=error,
            )

        await asyncio.sleep(120.0)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.create_task(run_parsing_loop())
    loop.run_forever()
