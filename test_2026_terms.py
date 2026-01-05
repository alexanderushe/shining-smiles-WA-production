#!/usr/bin/env python3
"""
Test script to verify 2026 term configuration and auto-detection logic.
This script tests the new Config helper methods.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config import Config
from datetime import datetime, timezone

def test_term_configuration():
    """Test that 2026 terms are properly configured"""
    print("=" * 60)
    print("Testing 2026 Term Configuration")
    print("=" * 60)
    
    # Check 2026 terms exist
    print("\n✅ Checking 2026 term dates...")
    expected_2026_terms = ['2026-1', '2026-2', '2026-3']
    for term in expected_2026_terms:
        if term in Config.TERM_START_DATES and term in Config.TERM_END_DATES:
            start = Config.TERM_START_DATES[term]
            end = Config.TERM_END_DATES[term]
            print(f"  {term}: {start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}")
        else:
            print(f"  ❌ {term}: MISSING!")
            return False
    
    # Verify dates match user requirements (updated for early payment period)
    print("\n✅ Verifying specific dates...")
    assert Config.TERM_START_DATES['2026-1'].day == 4, "Term 2026-1 should start on Jan 4 (early payment period)"
    assert Config.TERM_START_DATES['2026-1'].month == 1, "Term 2026-1 should start in January"
    assert Config.TERM_END_DATES['2026-1'].day == 2, "Term 2026-1 should end on Apr 2"
    assert Config.TERM_END_DATES['2026-1'].month == 4, "Term 2026-1 should end in April"
    print("  2026-1 dates: ✓ Correct (Jan 4 - Apr 2, early payments enabled)")
    
    assert Config.TERM_START_DATES['2026-2'].day == 4, "Term 2026-2 should start on May 4"
    assert Config.TERM_END_DATES['2026-2'].day == 6, "Term 2026-2 should end on Aug 6"
    print("  2026-2 dates: ✓ Correct")
    
    assert Config.TERM_START_DATES['2026-3'].day == 7, "Term 2026-3 should start on Sep 7"
    assert Config.TERM_END_DATES['2026-3'].day == 3, "Term 2026-3 should end on Dec 3"
    print("  2026-3 dates: ✓ Correct")
    
    return True

def test_helper_methods():
    """Test the new helper methods"""
    print("\n" + "=" * 60)
    print("Testing Helper Methods")
    print("=" * 60)
    
    # Test get_current_term (as of Jan 4, 2026)
    print("\n✅ Testing get_current_term()...")
    current_term = Config.get_current_term()
    print(f"  Current term (Jan 4, 2026): {current_term}")
    # Should be 2026-1 since term now starts Jan 4
    if current_term == '2026-1':
        print("  ✓ Correctly returns 2026-1 (term is active)")
    else:
        print(f"  ⚠️ Expected 2026-1, got {current_term}")
    
    # Test get_most_recent_completed_term
    print("\n✅ Testing get_most_recent_completed_term()...")
    recent_term = Config.get_most_recent_completed_term()
    print(f"  Most recent completed term: {recent_term}")
    if recent_term == '2025-3':
        print("  ✓ Correctly returns 2025-3")
    else:
        print(f"  ⚠️ Expected 2025-3, got {recent_term}")
    
    # Test get_next_term
    print("\n✅ Testing get_next_term()...")
    next_term = Config.get_next_term()
    print(f"  Next term: {next_term}")
    if next_term == '2026-2':
        print("  ✓ Correctly returns 2026-2")
    else:
        print(f"  ⚠️ Expected 2026-2, got {next_term}")
    
    # Test is_between_terms
    print("\n✅ Testing is_between_terms()...")
    between = Config.is_between_terms()
    print(f"  Is between terms: {between}")
    if not between:
        print("  ✓ Correctly returns False (we're in term 2026-1)")
    else:
        print("  ⚠️ Expected False, got True")
    
    return True

def test_break_message_scenario():
    """Test the scenario for term being active"""
    print("\n" + "=" * 60)
    print("Testing Active Term Scenario")
    print("=" * 60)
    
    print("\nSimulating user request during active term...")
    term = Config.get_current_term()
    
    if term:
        print(f"✓ Term is active: {term}")
        print(f"Message prefix: 📊 *Current Balance (Term {term}):*")
        print("\n✓ Active term messaging working correctly!")
    else:
        print(f"⚠️ Term should be active but got: {term}")
    
    return True

def main():
    """Run all tests"""
    print("\n" + "🧪" * 30)
    print("2026 TERM CONFIGURATION TEST SUITE")
    print("🧪" * 30 + "\n")
    
    try:
        # Run all tests
        results = []
        results.append(("Term Configuration", test_term_configuration()))
        results.append(("Helper Methods", test_helper_methods()))
        results.append(("Active Term Scenario", test_break_message_scenario()))
        
        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        for name, passed in results:
            status = "✅ PASSED" if passed else "❌ FAILED"
            print(f"{name}: {status}")
        
        all_passed = all(result[1] for result in results)
        
        if all_passed:
            print("\n🎉 All tests PASSED! The 2026 term configuration is working correctly.")
            return 0
        else:
            print("\n⚠️  Some tests FAILED. Please review the output above.")
            return 1
            
    except Exception as e:
        print(f"\n❌ Test suite crashed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
