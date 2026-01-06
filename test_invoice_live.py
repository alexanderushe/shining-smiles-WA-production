#!/usr/bin/env python3
"""
Test invoice generation with real student data from SMS API.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from services.invoice_service import generate_invoice
from api.sms_client import SMSClient
from utils.database import init_db
import uuid

# Test with real student
STUDENT_ID = "SSC20257939"
TERM = "2026-1"
WHATSAPP_NUMBER = "+263771234567"  # Test number
REQUEST_ID = str(uuid.uuid4())

print("=" * 70)
print("INVOICE GENERATION - LIVE API TEST")
print("=" * 70)
print(f"Student ID: {STUDENT_ID}")
print(f"Term: {TERM}")
print(f"Request ID: {REQUEST_ID}")
print("=" * 70 + "\n")

try:
    # Initialize session
    session = init_db()
    
    print("🔄 Fetching student data from SMS API...")
    
    # Generate invoice
    result, status_code = generate_invoice(
        student_id=STUDENT_ID,
        term=TERM,
        whatsapp_number=WHATSAPP_NUMBER,
        request_id=REQUEST_ID
    )
    
    if status_code == 200:
        print("✅ Invoice generated successfully!\n")
        print("📄 Invoice Details:")
        print(f"   - Invoice Number: {result['invoice_number']}")
        print(f"   - Total Amount: ${result['total_amount']:.2f}")
        print(f"   - Issue Date: {result['issued_date']}")
        print(f"   - Due Date: {result['due_date']}")
        print(f"   - PDF URL: {result['pdf_url'][:80]}...")
        if result.get('is_resend'):
            print("   ℹ️  This is a resend of existing invoice")
        
        # Download and save PDF locally for review
        import requests
        pdf_response = requests.get(result['pdf_url'])
        output_file = f"test_invoice_{STUDENT_ID}.pdf"
        with open(output_file, 'wb') as f:
            f.write(pdf_response.content)
        
        print(f"\n✅ PDF saved to: {output_file}")
        print(f"📂 File size: {len(pdf_response.content):,} bytes")
        
        # Open it
        os.system(f"open {output_file}")
        
    else:
        print(f"❌ Invoice generation failed (Status: {status_code})")
        print(f"Error: {result.get('error', 'Unknown error')}")
        
except Exception as e:
    print(f"\n❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
finally:
    if 'session' in locals():
        session.remove()

print("\n" + "=" * 70)
