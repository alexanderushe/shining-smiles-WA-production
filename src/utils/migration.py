import logging
from sqlalchemy import text
from utils.database import init_db
from utils.logger import setup_logger

logger = setup_logger(__name__)

def run_migration_logic():
    logger.info("🚀 Starting database migration from Lambda...")
    session = init_db()
    try:
        logger.info("🔍 Checking if 'last_total_paid' column exists...")
        # Check if column exists
        result = session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='student_contacts' AND column_name='last_total_paid';"
        ))
        if result.fetchone():
            logger.info("✅ Column 'last_total_paid' already exists.")
            return "Column 'last_total_paid' already exists."
        else:
            logger.info("➕ Adding 'last_total_paid' column...")
            session.execute(text("ALTER TABLE student_contacts ADD COLUMN last_total_paid FLOAT DEFAULT 0.0;"))
            session.commit()
            logger.info("✅ Migration successful: Added 'last_total_paid' column.")
            return "Migration successful: Added 'last_total_paid' column."
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        session.rollback()
        raise e
    finally:
        session.close()
        logger.info("👋 Migration script finished.")
