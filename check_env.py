
import os
import sys

# Add src to path just in case we need to import config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

try:
    from config import Config
    
    print("Checking environment variables...")
    if Config.SMS_API_KEY:
        print("✅ SMS_API_KEY is present.")
    else:
        print("❌ SMS_API_KEY is MISSING.")
        
    if Config.SMS_API_BASE_URL:
        print(f"✅ SMS_API_BASE_URL is set.")
    else:
        print("❌ SMS_API_BASE_URL is MISSING.")

except ImportError:
    print("Could not import config.")
except Exception as e:
    print(f"Error checking config: {e}")
