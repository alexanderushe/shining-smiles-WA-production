-- Transport Pass Table Migration
-- Run this on the shining_smiles database

CREATE TABLE IF NOT EXISTS transport_passes (
    id SERIAL PRIMARY KEY,
    pass_id VARCHAR(50) UNIQUE NOT NULL,
    student_id VARCHAR(50) NOT NULL,
    term VARCHAR(50) NOT NULL,
    route_type VARCHAR(20) NOT NULL,
    service_type VARCHAR(20) NOT NULL,
    amount_paid FLOAT NOT NULL,
    issued_date TIMESTAMP WITH TIME ZONE NOT NULL,
    expiry_date TIMESTAMP WITH TIME ZONE NOT NULL,
    whatsapp_number VARCHAR(20),
    pdf_path VARCHAR(255),
    qr_path VARCHAR(255),
    status VARCHAR(20) DEFAULT 'active',
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (student_id) REFERENCES student_contacts(student_id) ON DELETE CASCADE
);

-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_transport_passes_student_term ON transport_passes(student_id, term);
CREATE INDEX IF NOT EXISTS idx_transport_passes_pass_id ON transport_passes(pass_id);
CREATE INDEX IF NOT EXISTS idx_transport_passes_status ON transport_passes(status);

-- Verify table creation
SELECT 'transport_passes table created successfully!' as status;
