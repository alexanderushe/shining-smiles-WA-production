-- Invoice Table Migration
-- Run this on the shining_smiles database

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    student_id VARCHAR(20) NOT NULL,
    term VARCHAR(10) NOT NULL,
    issued_date TIMESTAMP WITH TIME ZONE NOT NULL,
    due_date TIMESTAMP WITH TIME ZONE NOT NULL,
    whatsapp_number VARCHAR(20),
    total_amount FLOAT,
    pdf_path VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_invoices_student_term ON invoices(student_id, term);
CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number);
CREATE INDEX IF NOT EXISTS idx_invoices_whatsapp ON invoices(whatsapp_number);

-- Verify table creation
SELECT 'invoices table created successfully!' as status;
