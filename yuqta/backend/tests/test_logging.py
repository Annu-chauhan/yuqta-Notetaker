import logging

from app.core.logging import _RedactQueryStrings


def test_presigned_url_credentials_are_not_logged() -> None:
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, 'HTTP Request: %s %s "%s"',
                               ("GET", "https://bucket.s3.amazonaws.com/t.json?AWSAccessKeyId=AKIA&Signature=abc", "HTTP/1.1 200 OK"), None)
    _RedactQueryStrings().filter(record)
    message = record.getMessage()
    assert "Signature" not in message and "AKIA" not in message
    assert message == 'HTTP Request: GET https://bucket.s3.amazonaws.com/t.json?<redacted> "HTTP/1.1 200 OK"'
