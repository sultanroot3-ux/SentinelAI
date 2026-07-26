"""Helpers that keep credentials out of log output.

Log records get shipped to aggregators, tailed in shared terminals and captured
in support bundles, so anything written to a log should be assumed to travel
further than the host that produced it. Three kinds of value need scrubbing:

1. Connection URLs whose *userinfo* carries a password
   (``redis://sentinel:hunter2@cache:6379/0``). Only the password is secret;
   the host and scheme are the operationally useful part, so they are kept.

2. Endpoints whose *path* is itself the credential. Telegram puts the bot token
   in the path (``/bot<TOKEN>/sendMessage``) and a Discord webhook URL is a
   bearer credential in its entirety — for these the path must go, not the
   userinfo.

3. Third-party exception text. This is the subtle one: ``requests`` embeds the
   full request URL in the exception it raises, so

       raise_for_status()  ->  "401 Client Error: Unauthorized for url:
                                https://api.telegram.org/bot<TOKEN>/sendMessage"

   means a bare ``logger.exception("... failed")`` writes the bot token to the
   log even though the call site never logs the token itself. ``scrub`` removes
   known secret values from arbitrary text before it is logged.
"""
from urllib.parse import urlsplit, urlunsplit

MASK = "***"

# Below this length a "secret" is too short to blind-replace inside free text:
# masking every occurrence of a 2-character chat id would mangle the message
# without protecting anything worth protecting.
_MIN_SCRUBBABLE_LEN = 6


def redact_url(url: str | None) -> str:
    """Mask the password in a connection URL, keeping scheme/host/port/path.

    ``redis://user:pw@cache:6379/0`` -> ``redis://user:***@cache:6379/0``

    Anything unparseable is reported as such rather than echoed, so a malformed
    value in configuration cannot smuggle a secret into the log.
    """
    if not url:
        return "<unset>"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable-url>"

    if not parts.hostname or parts.password is None:
        # No credential to strip. Still avoid echoing something with no host
        # (e.g. a bare path) that we cannot reason about.
        return url if parts.hostname else "<unparseable-url>"

    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    userinfo = f"{parts.username}:{MASK}@" if parts.username else f":{MASK}@"
    return urlunsplit(
        (parts.scheme, f"{userinfo}{host}", parts.path, parts.query, parts.fragment)
    )


def redact_endpoint(url: str | None) -> str:
    """Keep only scheme://host for URLs whose path carries the credential.

    Used for Telegram and Discord, where the token/webhook secret lives in the
    path. The host is retained because "which service did we fail to reach" is
    the question a log reader actually has.
    """
    if not url:
        return "<unset>"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable-url>"
    if not parts.hostname:
        return "<unparseable-url>"
    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    return f"{parts.scheme}://{host}/{MASK}" if parts.scheme else f"{host}/{MASK}"


def scrub(value: object, *secrets: str | None) -> str:
    """Stringify ``value`` and replace every occurrence of each secret.

    Intended for exception text from libraries that echo request URLs. Secrets
    shorter than ``_MIN_SCRUBBABLE_LEN`` are ignored — see the note above.
    """
    text = value if isinstance(value, str) else str(value)
    for secret in secrets:
        if secret is None:
            continue
        secret = str(secret)
        if len(secret) >= _MIN_SCRUBBABLE_LEN:
            text = text.replace(secret, MASK)
    return text
