import sys
import os
import logging

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from utils.scheduler import check_all_payments, send_all_reminders
from utils.logger import setup_logger

# Setup logging to console
logger = setup_logger(__name__)
logging.getLogger().setLevel(logging.INFO)

def main():
    print("🚀 Starting manual trigger...")
    
    print("\n💳 Triggering Payment Checks...")
    try:
        check_all_payments()
        print("✅ Payment checks completed.")
    except Exception as e:
        print(f"❌ Payment checks failed: {e}")

    print("\n🔔 Triggering Reminders...")
    try:
        send_all_reminders()
        print("✅ Reminders completed.")
    except Exception as e:
        print(f"❌ Reminders failed: {e}")

if __name__ == "__main__":
    main()
