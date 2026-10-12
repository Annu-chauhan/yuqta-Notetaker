import logging

from app.core.logging import _RedactQueryStrings


def test_presigned_url_credentials_are_not_logged() -> None:
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, 'HTTP Request: %s %s "%s"',
                               ("GET", "https://bucket.s3.amazonaws.com/t.json?AWSAccessKeyId=AKIA&Signature=abc", "HTTP/1.1 200 OK"), None)
    _RedactQueryStrings().filter(record)
    message = record.getMessage()
    assert "Signature" not in message and "AKIA" not in message
    assert message == 'HTTP Request: GET https://bucket.s3.amazonaws.com/t.json?<redacted> "HTTP/1.1 200 OK"'


def test_oauth_callback_code_is_not_in_the_access_log() -> None:
    from app.core.logging import _RedactOAuthCallback

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("172.18.0.1:5", "GET", "/auth/google/callback?state=abc&code=4/secret", "1.1", 302), None)
    _RedactOAuthCallback().filter(record)
    assert "secret" not in record.getMessage() and "/auth/google/callback?<redacted>" in record.getMessage()
    other = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                              ("172.18.0.1:5", "GET", "/api/action-items?view=all", "1.1", 200), None)
    _RedactOAuthCallback().filter(other)
    assert "view=all" in other.getMessage()  # ordinary paths keep their query
