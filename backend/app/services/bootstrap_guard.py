"""Refuse to run production on the documented bootstrap credential.

The seeded `admin` account (app/main.py) is created with a published password so
a fresh install is reachable, and `must_change_password=True` prompts for
rotation at first login. A prompt is not a control — nothing prevents deploying
with the credential intact, and the value appears in README.md, docs/INSTALL.md,
docs/ADMIN_MANUAL.md and docs/API_CONTRACT.md, so it is not a secret an attacker
has to discover.

This turns the prompt into a boot condition: production refuses to start while
any account still verifies against it. Development only warns, because a
throwaway dev database on the default credential is the intended experience.

Deliberately verifies rather than comparing hashes: bcrypt salts every hash, so
the stored value differs per account and a string comparison would catch
nothing.
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password
from app.models.models import User

logger = logging.getLogger("sentinelai.bootstrap")

# Must stay in step with the seed in app/main.py.
BOOTSTRAP_PASSWORD = "admin123"


class BootstrapCredentialError(RuntimeError):
    """Raised when production would start on the published default password."""


def accounts_on_bootstrap_password(db: Session) -> list[str]:
    """Usernames whose password is still the documented bootstrap value.

    Checks every account, not just `admin`: a second account created with the
    same password is the same exposure.
    """
    found = []
    for user in db.query(User).all():
        try:
            if verify_password(BOOTSTRAP_PASSWORD, user.password_hash):
                found.append(user.username)
        except Exception:  # a malformed hash must not stop the scan
            logger.exception(
                "Could not verify the password hash for user id=%s", user.id
            )
    return found


def assert_no_bootstrap_credentials(db: Session) -> None:
    """Block production startup on the default credential; warn in development."""
    found = accounts_on_bootstrap_password(db)
    if not found:
        return

    names = ", ".join(sorted(found))
    if settings.is_production:
        # The account names are named so the operator knows what to rotate; the
        # password itself is not echoed. Startup failures reach aggregated logs
        # and crash reports, and writing the credential into every failed boot
        # is gratuitous even though the value is public.
        raise BootstrapCredentialError(
            "Refusing to start: these accounts still use the documented "
            f"bootstrap password: {names}. Rotate them before deploying "
            "(see docs/DEPLOYMENT_CHECKLIST.md)."
        )
    logger.warning(
        "These accounts still use the documented bootstrap password: %s. "
        "This is allowed in development; production will refuse to start.",
        names,
    )
