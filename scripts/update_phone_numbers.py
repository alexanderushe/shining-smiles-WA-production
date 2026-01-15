"""
One-time Lambda function to update student phone numbers.
Deploy this temporarily, run once, then delete.
"""
import json
import boto3
from sqlalchemy import create_engine, text

def lambda_handler(event, context):
    # Get DB credentials
    client = boto3.client('secretsmanager', region_name='us-east-2')
    secret = json.loads(client.get_secret_value(SecretId='shining-smiles-db-credentials')['SecretString'])
    
    db_url = f"postgresql+pg8000://{secret['username']}:{secret['password']}@{secret['host']}:{secret.get('port', 5432)}/{secret['dbname']}"
    engine = create_engine(db_url)
    
    results = []
    
    with engine.connect() as conn:
        # Query SSC20258052 before update
        query_result = conn.execute(text("""
            SELECT student_id, firstname, lastname, guardian_mobile_number, preferred_phone_number
            FROM student_contacts 
            WHERE student_id = 'SSC20258052'
        """))
        results.append("=== BEFORE UPDATE ===")
        for row in query_result:
            results.append(f"SSC20258052: {row}")
        
        # Update SSC20258052 with +263711206287 (all phone fields)
        conn.execute(text("""
            UPDATE student_contacts 
            SET preferred_phone_number = '+263711206287',
                guardian_mobile_number = '+263711206287',
                student_mobile = '+263711206287',
                last_updated = CURRENT_TIMESTAMP
            WHERE student_id = 'SSC20258052'
        """))
        results.append("✅ SSC20258052 updated with +263711206287")
        
        conn.commit()
        
        # Verify changes
        query_result = conn.execute(text("""
            SELECT student_id, firstname, lastname, guardian_mobile_number, preferred_phone_number
            FROM student_contacts 
            WHERE student_id = 'SSC20258052'
        """))
        results.append("=== AFTER UPDATE ===")
        for row in query_result:
            results.append(f"SSC20258052: {row}")
    
    return {
        'statusCode': 200,
        'body': json.dumps(results, indent=2)
    }

