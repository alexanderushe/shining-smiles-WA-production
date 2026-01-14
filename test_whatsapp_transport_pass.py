"""
Test Transport Pass via WhatsApp Webhook Simulation

This simulates a real WhatsApp Cloud API webhook message
to test the transport pass feature end-to-end.
"""

import requests
import json

# Lambda endpoint
LAMBDA_URL = "http://localhost:9001/2015-03-31/functions/function/invocations"

# Test phone number (must be registered in database)
TEST_WHATSAPP = "+263711206287"  # Update as needed

def simulate_whatsapp_message(message_text):
    """
    Simulate a WhatsApp Cloud API webhook message
    """
    # This is the actual structure that WhatsApp Cloud API sends
    webhook_event = {
        "httpMethod": "POST",
        "body": json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "263771234567",
                            "phone_number_id": "PHONE_NUMBER_ID"
                        },
                        "contacts": [{
                            "profile": {"name": "Test User"},
                            "wa_id": TEST_WHATSAPP.replace("+", "")
                        }],
                        "messages": [{
                            "from": TEST_WHATSAPP.replace("+", ""),
                            "id": f"wamid.{int(__import__('time').time()*1000)}",
                            "timestamp": str(int(__import__('time').time())),
                            "text": {"body": message_text},
                            "type": "text"
                        }]
                    },
                    "field": "messages"
                }]
            }]
        })
    }
    
    return webhook_event


def test_transport_pass_via_whatsapp():
    """
    Test the complete WhatsApp bot flow for transport pass
    """
    print("=" * 70)
    print("🚌 TRANSPORT PASS - WHATSAPP WEBHOOK TEST")
    print("=" * 70)
    
    print(f"\n📱 Simulating WhatsApp message from: {TEST_WHATSAPP}")
    print(f"💬 Message: '5' (Transport Pass option)")
    
    # Step 1: Send "5" to request transport pass
    webhook_event = simulate_whatsapp_message("5")
    
    print(f"\n📤 Sending webhook to Lambda...")
    
    try:
        response = requests.post(LAMBDA_URL, json=webhook_event, timeout=30)
        
        print(f"\n📡 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ Lambda executed successfully")
            print(f"Response: {json.dumps(result, indent=2)}")
            
            print(f"\n💡 What happened:")
            print(f"   1. Lambda received WhatsApp webhook")
            print(f"   2. Processed message '5'")  
            print(f"   3. Checked for transport fees in database")
            print(f"   4. Generated transport pass (if fees paid)")
            print(f"   5. Sent PDF via WhatsApp")
            
            print(f"\n🔍 Check:")
            print(f"   - Lambda logs: docker logs shining-smiles-lambda")
            print(f"   - Database: SELECT * FROM transport_passes ORDER BY issued_date DESC LIMIT 1;")
            print(f"   - S3 bucket: aws s3 ls s3://shining-smiles-transport-passes/")
            
            return True
        else:
            print(f"\n❌ Lambda Error: {response.status_code}")
            print(response.text)
            return False
            
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def check_lambda_logs():
    """Show recent Lambda logs"""
    print("\n" + "=" * 70)
    print("📋 Recent Lambda Logs")
    print("=" * 70)
    import subprocess
    result = subprocess.run(
        ["docker", "logs", "--tail", "50", "shining-smiles-lambda"],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)


if __name__ == "__main__":
    print("\n🧪 TRANSPORT PASS WHATSAPP SIMULATION TEST\n")
    
    print("⚠️  REQUIREMENTS:")
    print(f"   1. Phone {TEST_WHATSAPP} must be registered in database")
    print(f"   2. Student must have transport fee billed for Term 2026-1")
    print(f"   3. Docker containers must be running")
    print(f"   4. Database migration must be complete")
    
    print("\n📝 This test will:")
    print("   - Simulate WhatsApp message '5' to Lambda")
    print("   - Trigger transport pass handler")
    print("   - Show Lambda logs")
    
    response = input("\n▶️  Run test? (y/n): ")
    if response.lower() == 'y':
        success = test_transport_pass_via_whatsapp()
        
        print("\n" + "=" * 70)
        
        if success:
            # Show logs
            show_logs = input("\n📋 Show Lambda logs? (y/n): ")
            if show_logs.lower() == 'y':
                check_lambda_logs()
        
    print("\n" + "=" * 70)
    print("Test Complete!")
    print("=" * 70)
