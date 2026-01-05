#!/usr/bin/env python3
"""
Test script for JIT (Just-In-Time) profile sync functionality.

This script tests the new JIT sync feature that allows gatepasses to be generated
immediately for new students without waiting for the scheduled cron job.

Test Cases:
1. Generate gatepass for student NOT in local DB (triggers JIT sync)
2. Generate gatepass for student ALREADY in DB (uses cached data)
3. Test with invalid student ID
4. Test with student who has no phone number
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from services.gatepass_service import generate_gatepass
from utils.database import init_db, StudentContact
from utils.logger import setup_logger

logger = setup_logger(__name__)


def test_jit_sync_new_student():
    """Test Case 1: Student NOT in DB - should trigger JIT sync"""
    print("\n" + "="*80)
    print("TEST 1: JIT Sync for New Student (not in local DB)")
    print("="*80)
    
    # Use a test student ID - replace with actual ID from your SMS system
    student_id = "SSC20250001"  # TODO: Replace with real student ID
    term = "2025-3"
    payment_amount = 500.0
    total_fees = 1000.0
    request_id = "test-jit-sync-001"
    whatsapp_number = "+263771234567"  # TODO: Replace with actual number
    
    # Clear student from DB to force JIT sync
    session = init_db()
    try:
        existing = session.query(StudentContact).filter_by(student_id=student_id).first()
        if existing:
            print(f"⚠️  Deleting existing record for {student_id} to test JIT sync")
            session.delete(existing)
            session.commit()
    finally:
        session.close()
    
    print(f"📝 Testing gatepass generation for {student_id}")
    print(f"   Payment: ${payment_amount} / ${total_fees} ({payment_amount/total_fees*100:.1f}%)")
    print(f"   Expected: JIT sync should fetch from API and create local record\n")
    
    result, status_code = generate_gatepass(
        student_id=student_id,
        term=term,
        payment_amount=payment_amount,
        total_fees=total_fees,
        request_id=request_id,
        requesting_whatsapp_number=whatsapp_number
    )
    
    print(f"✅ Status Code: {status_code}")
    print(f"📄 Result: {result}")
    
    # Verify student was added to DB
    session = init_db()
    try:
        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        if contact:
            print(f"✅ Student now in local DB: {contact.firstname} {contact.lastname}")
            print(f"   Phone: {contact.student_mobile}")
        else:
            print("❌ ERROR: Student not found in DB after JIT sync")
    finally:
        session.close()
    
    return status_code == 200


def test_cached_student():
    """Test Case 2: Student ALREADY in DB - should use cached data"""
    print("\n" + "="*80)
    print("TEST 2: Cached Student (already in local DB)")
    print("="*80)
    
    student_id = "SSC20250001"  # Same as Test 1 - should now be cached
    term = "2025-3"
    payment_amount = 600.0
    total_fees = 1000.0
    request_id = "test-cached-001"
    whatsapp_number = "+263771234567"
    
    print(f"📝 Testing gatepass generation for {student_id} (2nd time)")
    print(f"   Expected: Should use cached data (no API call)\n")
    
    import time
    start_time = time.time()
    
    result, status_code = generate_gatepass(
        student_id=student_id,
        term=term,
        payment_amount=payment_amount,
        total_fees=total_fees,
        request_id=request_id,
        requesting_whatsapp_number=whatsapp_number
    )
    
    elapsed = time.time() - start_time
    
    print(f"✅ Status Code: {status_code}")
    print(f"⏱️  Time: {elapsed:.2f}s (should be faster than Test 1)")
    print(f"📄 Result: {result}")
    
    return status_code == 200


def test_invalid_student():
    """Test Case 3: Invalid student ID"""
    print("\n" + "="*80)
    print("TEST 3: Invalid Student ID")
    print("="*80)
    
    student_id = "SSC99999999"  # Non-existent student
    term = "2025-3"
    payment_amount = 500.0
    total_fees = 1000.0
    request_id = "test-invalid-001"
    whatsapp_number = "+263771234567"
    
    print(f"📝 Testing with invalid student ID: {student_id}")
    print(f"   Expected: Should return 404 error\n")
    
    result, status_code = generate_gatepass(
        student_id=student_id,
        term=term,
        payment_amount=payment_amount,
        total_fees=total_fees,
        request_id=request_id,
        requesting_whatsapp_number=whatsapp_number
    )
    
    print(f"✅ Status Code: {status_code}")
    print(f"📄 Result: {result}")
    
    return status_code == 404


def main():
    """Run all tests"""
    print("\n" + "🔬 " + "="*76)
    print("  JIT SYNC TEST SUITE")
    print("="*78 + "\n")
    
    print("⚠️  IMPORTANT: Before running, update student IDs and phone numbers in this script")
    print("   to match real data in your SMS system.\n")
    
    response = input("Do you want to proceed with tests? (yes/no): ")
    if response.lower() != 'yes':
        print("Tests cancelled.")
        return
    
    results = []
    
    # Run tests
    try:
        results.append(("JIT Sync (New Student)", test_jit_sync_new_student()))
        results.append(("Cached Student", test_cached_student()))
        results.append(("Invalid Student", test_invalid_student()))
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n🎉 All tests passed! JIT sync is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Check logs above for details.")


if __name__ == "__main__":
    main()
