from .base import * # noqa: F403

DEBUG = False

SECURE_SSL_REDIRECT = True

SESSION_COOKIE_SECURE = True
CRSF_COOKIE_SECURE = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https"
)
