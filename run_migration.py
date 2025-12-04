import sys
import os
import logging
from sqlalchemy import text

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from utils.database import init_db
from utils.logger import setup_logger

logger = setup_logger(__name__)
logging.getLogger().setLevel(logging.INFO)

def run_migration():
    print("🚀 Starting database migration...")
    session = init_db()
    try:
        print("🔍 Checking if 'last_total_paid' column exists...")
        # Check if column exists
        result = session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='student_contacts' AND column_name='last_total_paid';"
        ))
        if result.fetchone():
            print("✅ Column 'last_total_paid' already exists.")
        else:
            print("➕ Adding 'last_total_paid' column...")
            session.execute(text("ALTER TABLE student_contacts ADD COLUMN last_total_paid FLOAT DEFAULT 0.0;"))
            session.commit()
            print("✅ Migration successful: Added 'last_total_paid' column.")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        session.rollback()
    finally:
        session.close()
        print("👋 Migration script finished.")

if __name__ == "__main__":
    run_migration()
