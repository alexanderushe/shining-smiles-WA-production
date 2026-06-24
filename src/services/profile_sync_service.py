"""DEPRECATED (W2.4).

The nightly profile sync against the legacy school system is retired — the SaaS
is the source of truth and the bot queries it live. Kept as a no-op stub so any
lingering import does not crash. Remove once all references are gone.
"""
from utils.logger import setup_logger

logger = setup_logger(__name__)


def sync_student_profiles(*args, **kwargs):
    logger.info("sync_student_profiles is deprecated (W2.4); SaaS is source of truth. No-op.")
    return {"status": "deprecated", "updated": 0,
            "message": "Profile sync retired; SaaS is the source of truth"}
