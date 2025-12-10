import sys
import os
import datetime

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

try:
    from utils.database import init_db, StudentContact
    from sqlalchemy import desc

    print("Connecting to database...")
    session = init_db()

    # defined timeframe (last 24 hours) as a rough check for "today"
    now = datetime.datetime.now(datetime.timezone.utc)
    one_day_ago = now - datetime.timedelta(days=1)

    print(f"Checking for updates since {one_day_ago}")

    # Query latest updates
    recent_updates = session.query(StudentContact).filter(
        StudentContact.last_updated >= one_day_ago
    ).order_by(desc(StudentContact.last_updated)).limit(10).all()

    count_recent = session.query(StudentContact).filter(
        StudentContact.last_updated >= one_day_ago
    ).count()
    
    total_count = session.query(StudentContact).count()

    print(f"Total synced students in database: {total_count}")
    print(f"Found {count_recent} records updated in the last 24 hours.")

    if recent_updates:
        print("Latest updates:")
        for contact in recent_updates:
            print(f"- Student {contact.student_id}: {contact.last_updated}")
    else:
        print("No updates found in the last 24 hours.")
        print("Please check if the cron jobs (AWS EventBridge) are enabled.")

except Exception as e:
    print(f"Error verifying execution: {e}")
