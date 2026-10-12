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


class _RedactOAuthCallback(logging.Filter):
    """uvicorn's access log prints the request path; Google's callback carries the sign-in code in it."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and str(args[2]).startswith("/auth/google/callback?"):
            record.args = (*args[:2], "/auth/google/callback?<redacted>", *args[3:])
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # httpx logs every request URL at INFO; keep the URLs but never their query strings.
    logging.getLogger("httpx").addFilter(_RedactQueryStrings())
    logging.getLogger("uvicorn.access").addFilter(_RedactOAuthCallback())
