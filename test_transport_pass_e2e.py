"""
End-to-End Transport Pass Test
This will actually generate a PDF and show you where it's stored.
"""

import requests
import json
from datetime import datetime

# Test configuration
BASE_URL = "http://localhost:9001/2015-03-31/functions/function/invocations"
TEST_STUDENT_ID = "SSC20246303"  # Update with real student
TEST_TERM = "2026-1"
TEST_WHATSAPP = "+263771234567"  # Update with test number

def test_full_transport_pass_generation():
    """
    Test the complete flow:
    1. Call generate_transport_pass endpoint
    2. Check response
    3. Verify PDF was created
    4. Show PDF location
    """
    print("=" * 70)
    print("🚌 FULL TRANSPORT PASS GENERATION TEST")
    print("=" * 70)
    
    # Create the Lambda event for transport pass generation
    payload = {
        "student_id": TEST_STUDENT_ID,
        "term": TEST_TERM,
        "route_type": "local",
        "service_type": "1_way",
        "amount_paid": 100.0,
        "whatsapp_number": TEST_WHATSAPP,
        "skip_whatsapp": True  # Don't send via WhatsApp for testing
    }
    
    print(f"\n📝 Test Configuration:")
    print(f"   Student ID: {TEST_STUDENT_ID}")
    print(f"   Term: {TEST_TERM}")
    print(f"   Route: Local 1-Way")
    print(f"   Amount: $100.00")
    print(f"   WhatsApp: {TEST_WHATSAPP}")
    
    # Call the Lambda endpoint directly (bypassing WhatsApp bot)
    print(f"\n🔌 Calling Generate Transport Pass Endpoint...")
    
    event = {
        "body": json.dumps(payload),
        "httpMethod": "POST",
        "path": "/generate-transport-pass",
        "headers": {"Content-Type": "application/json"}
    }
    
    try:
        response = requests.post(BASE_URL, json=event, timeout=30)
        
        print(f"\n📡 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            lambda_response = response.json()
            print(f"\n📦 Lambda Response:")
            print(json.dumps(lambda_response, indent=2))
            
            # Check if we got a proper response body
            if "body" in lambda_response and lambda_response["body"] != "OK":
                body = json.loads(lambda_response["body"])
                print(f"\n📄 API Response Body:")
                print(json.dumps(body, indent=2))
                
                # Check for success
                if lambda_response.get("statusCode") == 200:
                    print("\n" + "=" * 70)
                    print("✅ SUCCESS! Transport Pass Generated!")
                    print("=" * 70)
                    print(f"\n📋 Pass Details:")
                    print(f"   Pass ID: {body.get('pass_id')}")
                    print(f"   Student: {body.get('student_id')}")
                    print(f"   Route: {body.get('route')}")
                    print(f"   Service: {body.get('service')}")
                    print(f"   Issued: {body.get('issued_date')}")
                    print(f"   Expires: {body.get('expiry_date')}")
                    print(f"   Status: {body.get('status')}")
                    
                    if "pdf_url" in body:
                        print(f"\n📎 PDF Location:")
                        print(f"   URL: {body['pdf_url']}")
                        print(f"\n   ℹ️  This is a presigned S3 URL valid for 1 hour")
                        print(f"   ℹ️  You can download it directly from this URL")
                    
                    if "qr_code" in body:
                        print(f"\n🔲 QR Code:")
                        print(f"   Data: {body['qr_code'][:100]}...")
                    
                    print(f"\n💾 Database Record:")
                    print(f"   Pass saved to transport_passes table")
                    print(f"   Query: SELECT * FROM transport_passes WHERE pass_id = '{body.get('pass_id')}'")
                    
                    return True
                    
                elif lambda_response.get("statusCode") == 402:
                    print("\n⚠️  PARTIAL PAYMENT DETECTED")
                    print(f"   Paid: ${body.get('paid', 0):.2f}")
                    print(f"   Required: ${body.get('required', 0):.2f}")
                    print(f"   Outstanding: ${body.get('outstanding', 0):.2f}")
                    return False
                else:
                    print(f"\n❌ ERROR: {body.get('error', 'Unknown error')}")
                    return False
            else:
                print("\n❌ ERROR: Lambda returned 'OK' instead of JSON")
                print("   This means the route might not be registered properly")
                return False
        else:
            print(f"\n❌ ERROR: HTTP {response.status_code}")
            print(response.text)
            return False
            
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Cannot connect to Lambda")
        print("   Make sure Docker containers are running:")
        print("   docker ps")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def check_database_record(pass_id):
    """Check if the transport pass was saved to the database"""
    print("\n" + "=" * 70)
    print("🔍 Checking Database Record")
    print("=" * 70)
    
    print(f"\nRun this in your database:")
    print(f"  docker exec -it shining-smiles-db psql -U postgres -d shining_smiles")
    print(f"  SELECT * FROM transport_passes WHERE pass_id = '{pass_id}';")


if __name__ == "__main__":
    print("\n🧪 TRANSPORT PASS END-TO-END TEST")
    print("\n⚠️  IMPORTANT: Update the following before running:")
    print(f"   - TEST_STUDENT_ID (currently: {TEST_STUDENT_ID})")
    print(f"   - TEST_WHATSAPP (currently: {TEST_WHATSAPP})")
    print(f"   - Ensure student has transport fee in database")
    
    response = input("\n▶️  Run test? (y/n): ")
    if response.lower() == 'y':
        success = test_full_transport_pass_generation()
        
        if not success:
            print("\n💡 Troubleshooting:")
            print("   1. Check Docker containers: docker ps")
            print("   2. Check Lambda logs: docker logs shining-smiles-lambda")
            print("   3. Verify database migration: docker exec shining-smiles-db psql -U postgres -d shining_smiles -c '\\dt'")
            print("   4. Check student has transport fee in billing")
    
    print("\n" + "=" * 70)
    print("Test Complete!")
    print("=" * 70)
