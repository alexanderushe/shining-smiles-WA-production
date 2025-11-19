# src/services/reminder_logic.py
from datetime import datetime, timezone
from config import get_config
from utils.logger import setup_logger

logger = setup_logger(__name__)
cfg = get_config()

def should_send_reminder(user_state, term):
    """Decides whether a reminder should be sent based on term progression and history."""
    now = datetime.now(timezone.utc)
    
    if not user_state:
        logger.info(f"No user_state for term {term}, sending reminder")
        return True

    if not user_state.last_updated:
        logger.info(f"No last_updated for user_state, sending reminder for term {term}")
        return True

    try:
        # Validate term
        if term not in cfg.TERM_START_DATES:
            logger.error(f"Invalid term code: {term}")
            raise ValueError(f"Invalid term code: {term}")

        # Calculate weeks
        weeks_left = cfg.weeks_remaining(term)
        weeks_elapsed = cfg.weeks_elapsed(term)
        end_date = cfg.term_end_date(term)
        start_date = cfg.TERM_START_DATES[term]

        # Log for debugging
        logger.info(f"Term {term}: weeks_left={weeks_left}, weeks_elapsed={weeks_elapsed}, now={now}, start_date={start_date}, end_date={end_date}")

        # Final 4 weeks of term = increase intensity
        days_since_last = (now - user_state.last_updated).days
        if weeks_left <= 2:
            logger.info(f"Term {term} has {weeks_left} weeks left, days since last reminder: {days_since_last} (>= 2)")
            return days_since_last >= 2
        elif weeks_left <= 4:
            logger.info(f"Term {term} has {weeks_left} weeks left, days since last reminder: {days_since_last} (>= 4)")
            return days_since_last >= 4
        elif weeks_elapsed >= 2:
            logger.info(f"Term {term} has {weeks_elapsed} weeks elapsed, days since last reminder: {days_since_last} (>= 7)")
            return days_since_last >= 7
        else:
            logger.info(f"Term {term} too early (weeks elapsed: {weeks_elapsed})")
            return False
    except Exception as e:
        logger.error(f"Error in should_send_reminder for term {term}: {str(e)}")
        raise

def generate_reminder_message(fullname, student_id, balance, term):
    """Generate a reminder message with dynamic tone and due date."""
    try:
        weeks_left = cfg.weeks_remaining(term)
        end_date = cfg.term_end_date(term).strftime("%B %d, %Y")
    except ValueError as e:
        logger.error(f"Invalid term code {term}: {str(e)}")
        raise

    if weeks_left > 4:
        tone = "gentle"
    elif weeks_left > 2:
        tone = "firm"
    else:
        tone = "final"

    logger.info(f"Generating {tone} reminder for {student_id}, term {term}, weeks left: {weeks_left}")
    if tone == "gentle":
        return (
            f"Hi {fullname}, this is a friendly reminder that your child ({student_id}) has an outstanding balance of ${balance} "
            f"for Term {term}. We’d appreciate early settlement by {end_date} to keep things running smoothly. Thank you!"
        )
    elif tone == "firm":
        return (
            f"Dear {fullname}, your child ({student_id}) still has an outstanding balance of ${balance} for Term {term}. "
            f"Please make payment by {end_date} to avoid end-of-term disruptions."
        )
    else:
        return (
            f"⚠️ URGENT: {fullname}, a balance of ${balance} is still unpaid for {student_id} (Term {term}). "
            f"Failure to clear by {end_date} may affect your child’s access to school services."
        )