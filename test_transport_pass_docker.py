"""
Test Transport Pass Feature in Docker

This script tests the transport pass generation with the Docker setup.
Lambda is running on port 9001.
"""

import requests
import json

# Docker Lambda API Gateway endpoint
BASE_URL = "http://localhost:9001/2015-03-31/functions/function/invocations"

def test_transport_pass_generation():
    """Test transport pass generation via Lambda"""
    print("=" * 60)
    print("Testing Transport Pass Generation (Docker)")
    print("=" * 60)
    
    # Simulate API Gateway event for transport pass generation
    event = {
        "body": json.dumps({
            "student_id": "SSC20246303",  # Update with real student ID
            "term": "2026-1",
            "route_type": "local",
            "service_type": "1_way",
            "amount_paid": 100.0,
            "whatsapp_number": "+263771234567",  # Update with test number
            "skip_whatsapp": True
        }),
        "httpMethod": "POST",
        "path": "/generate-transport-pass",
        "headers": {
            "Content-Type": "application/json"
        }
    }
    
    print(f"\nLambda URL: {BASE_URL}")
    print(f"Event: {json.dumps(event, indent=2)}")
    
    try:
        response = requests.post(BASE_URL, json=event, timeout=30)
        print(f"\nResponse Status: {response.status_code}")
        
        if response.status_code == 200:
            lambda_response = response.json()
            print(f"Lambda Response: {json.dumps(lambda_response, indent=2)}")
            
            if "body" in lambda_response:
                body = json.loads(lambda_response["body"])
                print(f"\nAPI Response Body: {json.dumps(body, indent=2)}")
                
                if lambda_response.get("statusCode") == 200:
                    print("\n✅ SUCCESS: Transport pass generated!")
                    if "pass_id" in body:
                        print(f"   Pass ID: {body['pass_id']}")
                        print(f"   Route: {body.get('route')}")
                        print(f"   Expiry: {body.get('expiry_date')}")
                elif lambda_response.get("statusCode") == 402:
                    print("\n⚠️  PARTIAL PAYMENT")
                    print(f"   Paid: ${body.get('paid', 0):.2f}")
                    print(f"   Required: ${body.get('required', 0):.2f}")
                    print(f"   Outstanding: ${body.get('outstanding', 0):.2f}")
                else:
                    print(f"\n❌ ERROR: {body.get('error', 'Unknown error')}")
        else:
            print(f"Lambda invocation failed: {response.text}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")


def test_fee_parsing():
    """Test the fee parsing function directly"""
    print("\n" + "=" * 60)
    print("Testing Fee Parsing & Validation")
    print("=" * 60)
    
    # Import the service locally to test
    import sys
    sys.path.insert(0, 'src')
    
    try:
        from services.transport_pass_service import parse_and_validate_transport_fee
        
        test_cases = [
            ("Transport Local 2 Way", 180.0, True, "Full payment"),
            ("Transport Local 1 Way", 100.0, True, "Full payment"),
            ("Transport Hatfield One Way", 100.0, True, "Hatfield normalized to Local"),
            ("Transport Chitungwiza 2 Way", 200.0, True, "Full payment"),
            ("Transport CBD", 200.0, True, "Full payment"),
            ("Transport Local 1 Way", 50.0, False, "Partial payment"),
        ]
        
        for fee_type, amount, expected_paid, description in test_cases:
            print(f"\n{description}")
            print(f"  Fee: {fee_type} - ${amount:.2f}")
            
            result = parse_and_validate_transport_fee(fee_type, amount)
            
            if result:
                route, service, is_paid, expected = result
                status = "✅" if is_paid == expected_paid else "❌"
                print(f"  {status} Route: {route}, Service: {service}")
                print(f"     Expected: ${expected:.2f}, Paid: {is_paid}")
            else:
                print(f"  ❌ Not recognized as transport fee")
                
    except ImportError as e:
        print(f"Cannot import service: {e}")
        print("Skipping fee parsing test")


if __name__ == "__main__":
    print("\n🚌 TRANSPORT PASS DOCKER TESTING\n")
    
    # Test 1: Fee parsing (local test)
    test_fee_parsing()
    
    # Test 2: Generate transport pass via Lambda
    print("\n\n📝 Make sure to update:")
    print("   - student_id with a real ID from your database")
    print("   - whatsapp_number with your test number")
    
    response = input("\nRun Lambda test? (y/n): ")
    if response.lower() == 'y':
        test_transport_pass_generation()
    
    print("\n" + "=" * 60)
    print("Testing Complete!")
    print("=" * 60)
