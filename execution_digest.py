"""Shared validation for the Apps Script SHA-256 digest wire format."""
import base64
import binascii
import re


_SHA256_B64URL_RE = re.compile(r'^[A-Za-z0-9_-]{43}$')


def is_canonical_sha256_b64url(value):
    """Accept only unpadded Base64 URL-safe encodings of exactly 32 bytes."""
    if not isinstance(value, str) or not _SHA256_B64URL_RE.fullmatch(value):
        return False
    try:
        decoded = base64.b64decode(value + '=', altchars=b'-_', validate=True)
    except (ValueError, binascii.Error):
        return False
    return (len(decoded) == 32 and
            base64.urlsafe_b64encode(decoded).decode('ascii').rstrip('=') == value)
