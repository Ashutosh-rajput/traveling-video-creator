import logging
import sys


# Frequently-polled status endpoints whose successful access logs are noise.
_QUIET_POLL_PATHS = ("generate-status", "upload-gdrive-status")


class _StatusPollFilter(logging.Filter):
    """Drop successful access-log lines for the frequently-polled status
    endpoints so the log isn't flooded during a render / Drive upload.
    Failures (HTTP >= 400) are still logged.

    Uvicorn access records carry args = (client, method, path, http_version, status).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 5:
            path = str(args[2])
            if any(p in path for p in _QUIET_POLL_PATHS):
                try:
                    if int(args[4]) < 400:
                        return False
                except (TypeError, ValueError):
                    pass
        return True


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    # Turn off verbose HTTP request logs from httpx and httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Silence the noisy status polls (render progress + Drive upload); keep failures.
    logging.getLogger("uvicorn.access").addFilter(_StatusPollFilter())

