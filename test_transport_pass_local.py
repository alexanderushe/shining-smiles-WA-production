"""
Test Transport Pass Feature Locally

This script tests the transport pass generation endpoint locally.
"""

import requests
import json
from datetime import datetime

# Test data
BASE_URL = "http://127.0.0.1:5000"  # Local Flask server
TEST_STUDENT_ID = "SSC20246303"  # Replace with a real student ID from your test DB
TEST_TERM = "2026-1"
TEST_WHATSAPP = "+263771234567"  # Replace with your test WhatsApp number

def test_generate_transport_pass():
    """Test generating a transport pass"""
    print("=" * 60)
    print("Testing Transport Pass Generation")
    print("=" * 60)
    
    url = f"{BASE_URL}/generate-transport-pass"
    payload = {
        "student_id": TEST_STUDENT_ID,
        "term": TEST_TERM,
        "route_type": "local",  # local, chitungwiza, or cbd
        "service_type": "1_way",  # 1_way, 2_way, or either_way
        "amount_paid": 100.0,  # Should match expected price for route/service
        "whatsapp_number": TEST_WHATSAPP,
        "skip_whatsapp": True  # Set to True for testing (skip WhatsApp sending)
    }
    
    print(f"\nRequest URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body:\n{json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS: Transport pass generated!")
            data = response.json()
            if "pass_id" in data:
                print(f"   Pass ID: {data['pass_id']}")
                print(f"   Expiry: {data.get('expiry_date')}")
        elif response.status_code == 402:
            print("\n⚠️  PARTIAL PAYMENT: Outstanding balance detected")
            data = response.json()
            print(f"   Paid: ${data.get('paid', 0):.2f}")
            print(f"   Required: ${data.get('required', 0):.2f}")
            print(f"   Outstanding: ${data.get('outstanding', 0):.2f}")
        else:
            print(f"\n❌ ERROR: {response.json().get('error', 'Unknown error')}")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to Flask server")
        print("   Make sure the Flask server is running: python app.py")
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")


def test_verify_transport_pass():
    """Test verifying a transport pass"""
    print("\n" + "=" * 60)
    print("Testing Transport Pass Verification")
    print("=" * 60)
    
    # You'll need to replace this with an actual pass_id from a generated pass
    test_pass_id = "TEST_PASS_ID_HERE"
    
    url = f"{BASE_URL}/verify-transport-pass"
    params = {
        "pass_id": test_pass_id,
        "whatsapp_number": TEST_WHATSAPP
    }
    
    print(f"\nRequest URL: {url}")
    print(f"Params: {params}")
    
    try:
        response = requests.get(url, params=params, timeout=10)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body:\n{json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS: Transport pass is valid!")
        else:
            print(f"\n❌ ERROR: {response.json().get('error', 'Unknown error')}")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to Flask server")
        print("   Make sure the Flask server is running: python app.py")
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")


def test_parse_and_validate():
    """Test fee parsing and validation"""
    print("\n" + "=" * 60)
    print("Testing Fee Parsing & Validation")
    print("=" * 60)
    
    from src.services.transport_pass_service import parse_and_validate_transport_fee
    
    test_cases = [
        ("Transport Local 2 Way", 180.0, True),
        ("Transport Local 1 Way", 100.0, True),
        ("Transport Hatfield One Way", 100.0, True),  # Should normalize to local
        ("Transport Chitungwiza 2 Way", 200.0, True),
        ("Transport CBD", 200.0, True),
        ("Transport Local 1 Way", 50.0, False),  # Partial payment
        ("Unknown Fee Type", 100.0, None),  # Should return None
    ]
    
    for fee_type, amount, expected_fully_paid in test_cases:
        print(f"\nTesting: {fee_type} - ${amount:.2f}")
        result = parse_and_validate_transport_fee(fee_type, amount)
        
        if result is None:
            print(f"  Result: Not recognized as transport fee")
            if expected_fully_paid is None:
                print(f"  ✅ PASS")
            else:
                print(f"  ❌ FAIL: Expected to be parsed")
        else:
            route_type, service_type, is_fully_paid, expected_amount = result
            print(f"  Route: {route_type}, Service: {service_type}")
            print(f"  Expected: ${expected_amount:.2f}")
            print(f"  Fully Paid: {is_fully_paid}")
            
            if is_fully_paid == expected_fully_paid:
                print(f"  ✅ PASS")
            else:
                print(f"  ❌ FAIL: Expected fully_paid={expected_fully_paid}")


if __name__ == "__main__":
    print("\n🚌 TRANSPORT PASS LOCAL TESTING\n")
    
    # Test 1: Fee parsing (doesn't require server)
    test_parse_and_validate()
    
    # Test 2: Generate transport pass (requires server running)
    print("\n\n📝 To test pass generation, make sure:")
    print("   1. Flask server is running (python app.py)")
    print("   2. Update TEST_STUDENT_ID with a real student from your DB")
    print("   3. Update TEST_WHATSAPP with your test number")
    
    response = input("\nRun pass generation test? (y/n): ")
    if response.lower() == 'y':
        test_generate_transport_pass()
    
    # Test 3: Verify pass (requires server and generated pass)
    # Uncomment once you have a pass_id to test
    # test_verify_transport_pass()
    
    print("\n" + "=" * 60)
    print("Testing Complete!")
    print("=" * 60)
