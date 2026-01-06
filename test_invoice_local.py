#!/usr/bin/env python3
"""
Local test script for invoice generation feature.
Tests PDF generation, S3 upload (if credentials available), and invoice logic.
"""

import sys
import os
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from services.invoice_service import (
    is_hot_meals_mandatory,
    generate_invoice_number,
    create_invoice_pdf,
    SCHOOL_INFO,
    BRANCH_ADDRESSES
)

def test_hot_meals_logic():
    """Test grade-based hot meals detection."""
    print("=" * 60)
    print("TEST 1: Hot Meals Mandatory Logic")
    print("=" * 60)
    
    test_cases = [
        ("ECD A", True),
        ("ECD B", True),
        ("Reception", True),
        ("Kindergarten", True),
        ("Grade 1", False),
        ("Grade 3", False),
        ("Form 2", False),
        ("Form 6", False),
    ]
    
    all_passed = True
    for grade, expected in test_cases:
        result = is_hot_meals_mandatory(grade)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"  {grade:20s} → Mandatory: {str(result):5s} (Expected: {str(expected):5s}) {status}")
        if result != expected:
            all_passed = False
    
    print(f"\n{' PASSED' if all_passed else '❌ FAILED'}\n")
    return all_passed


def test_invoice_numbering():
    """Test invoice number generation."""
    print("=" * 60)
    print("TEST 2: Invoice Number Generation")
    print("=" * 60)
    
    test_cases = [
        ("SSC001", "2026-1", 1, "INV-2026-1-SSC001-001"),
        ("SSC20246303", "2025-3", 1, "INV-2025-3-SSC20246303-001"),
        ("SSC999", "2026-2", 99, "INV-2026-2-SSC999-099"),
    ]
    
    all_passed = True
    for student_id, term, seq, expected in test_cases:
        result = generate_invoice_number(student_id, term, seq)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"  {result:35s} (Expected: {expected}) {status}")
        if result != expected:
            all_passed = False
    
    print(f"\n{'✅ PASSED' if all_passed else '❌ FAILED'}\n")
    return all_passed


def test_pdf_generation():
    """Test PDF creation without S3."""
    print("=" * 60)
    print("TEST 3: PDF Generation")
    print("=" * 60)
    
    # Mock invoice data
    invoice_data = {
        "invoice_number": "INV-2026-1-TEST001-001",
        "issued_date": "05 January 2026",
        "due_date": "12 January 2026",
        "student_name": "[SSC20246303] THANDO MUJENI",
        "student_id": "SSC20246303",
        "grade": "ECD A",
        "items": [
            {
                "description": "Tuition Fee - Term 2026-1 (ECD A)",
                "amount": 450.00,
                "mandatory": True,
                "qty": 1
            },
            {
                "description": "Hot Meals (Mandatory - ECD)",
                "amount": 50.00,
                "mandatory": True,
                "qty": 1
            },
            {
                "description": "Transport Service (Optional)",
                "amount": 120.00,
                "mandatory": False,
                "qty": 1
            }
        ],
        "total_amount": 620.00,
        "branch_address": BRANCH_ADDRESSES["default"]
    }
    
    output_path = "test_invoice.pdf"
    extra_log = {"test": True}
    
    try:
        # Create PDF
        result_path = create_invoice_pdf(invoice_data, output_path, extra_log)
        
        if os.path.exists(result_path):
            file_size = os.path.getsize(result_path)
            print(f"  ✅ PDF created successfully: {result_path}")
            print(f"  📄 File size: {file_size:,} bytes")
            print(f"  📋 Invoice details:")
            print(f"     - Number: {invoice_data['invoice_number']}")
            print(f"     - Student: {invoice_data['student_name']}")
            print(f"     - Grade: {invoice_data['grade']}")
            print(f"     - Total: ${invoice_data['total_amount']:.2f}")
            print(f"     - Items: {len(invoice_data['items'])}")
            print(f"\n  💡 Open '{output_path}' to review the PDF\n")
            print("✅ PASSED\n")
            return True
        else:
            print(f"  ❌ PDF file not created\n")
            print("❌ FAILED\n")
            return False
            
    except Exception as e:
        print(f"  ❌ Error: {str(e)}\n")
        import traceback
        traceback.print_exc()
        print("\n❌ FAILED\n")
        return False


def test_school_info():
    """Verify school configuration."""
    print("=" * 60)
    print("TEST 4: School Information Configuration")
    print("=" * 60)
    
    all_passed = True
    
    required_fields = [
        "name", "email_info", "email_admin", "tel",
        "bank_name", "account_name", "account_number", "currency"
    ]
    
    print("  School Info:")
    for field in required_fields:
        value = SCHOOL_INFO.get(field, "MISSING")
        status = "✅" if field in SCHOOL_INFO else "❌"
        print(f"    {status} {field:20s}: {value}")
        if field not in SCHOOL_INFO:
            all_passed = False
    
    print(f"\n  Branch Addresses:")
    for branch, address in BRANCH_ADDRESSES.items():
        print(f"    ✅ {branch:20s}: {address}")
    
    print(f"\n{'✅ PASSED' if all_passed else '❌ FAILED'}\n")
    return all_passed


def test_dependencies():
    """Check if required libraries are installed."""
    print("=" * 60)
    print("TEST 5: Dependencies Check")
    print("=" * 60)
    
    dependencies = {
        "fpdf": "fpdf2",
        "boto3": "boto3",
        "sqlalchemy": "sqlalchemy",
    }
    
    all_passed = True
    for module_name, package_name in dependencies.items():
        try:
            __import__(module_name)
            print(f"  ✅ {package_name:20s} - Installed")
        except ImportError:
            print(f"  ❌ {package_name:20s} - MISSING (install with: pip install {package_name})")
            all_passed = False
    
    print(f"\n{'✅ PASSED' if all_passed else '❌ FAILED'}\n")
    return all_passed


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("INVOICE FEATURE - LOCAL TESTING")
    print("=" * 60)
    print(f"Test Date: {datetime.now().strftime('%d %B %Y %H:%M:%S')}")
    print("=" * 60 + "\n")
    
    results = {
        "Dependencies": test_dependencies(),
        "Hot Meals Logic": test_hot_meals_logic(),
        "Invoice Numbering": test_invoice_numbering(),
        "School Info": test_school_info(),
        "PDF Generation": test_pdf_generation(),
    }
    
    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {test_name:25s}: {status}")
    
    all_passed = all(results.values())
    print("=" * 60)
    
    if all_passed:
        print("✅ ALL TESTS PASSED - Ready for deployment!")
        print("\nNext steps:")
        print("  1. Add school logo to src/static/school_logo.png")
        print("  2. Add school stamp to src/static/school_stamp.png")
        print("  3. Create S3 bucket: aws s3 mb s3://shining-smiles-invoices")
        print("  4. Run database migration (see deployment_notes.md)")
        print("  5. Deploy to Lambda via ./docker-deploy.sh")
    else:
        print("❌ SOME TESTS FAILED - Fix issues before deployment")
        print("\nPlease review the errors above and fix them.")
    
    print("=" * 60 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
