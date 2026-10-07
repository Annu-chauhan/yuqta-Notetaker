import logging
import re


# Pre-signed download URLs (e.g. Recall.ai transcripts on S3) carry temporary credentials in the query string.
_QUERY = re.compile(r"(https?://[^\s?\"']+)\?[^\s\"']*")


class _RedactQueryStrings(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "?" in message:
            record.msg, record.args = _QUERY.sub(r"\1?<redacted>", message), None
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # httpx logs every request URL at INFO; keep the URLs but never their query strings.
    logging.getLogger("httpx").addFilter(_RedactQueryStrings())
