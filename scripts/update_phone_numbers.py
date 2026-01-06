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
        # Query SSC20257279 first
        query_result = conn.execute(text("""
            SELECT student_id, firstname, lastname, guardian_mobile_number, preferred_phone_number
            FROM student_contacts 
            WHERE student_id = 'SSC20257279'
        """))
        for row in query_result:
            results.append(f"SSC20257279: {row}")
        
        # Query SSC20247124
        query_result = conn.execute(text("""
            SELECT student_id, firstname, lastname, guardian_mobile_number, preferred_phone_number
            FROM student_contacts 
            WHERE student_id = 'SSC20247124'
        """))
        for row in query_result:
            results.append(f"SSC20247124: {row}")
        
        # Update SSC20247124 - add +263711206287
        conn.execute(text("""
            UPDATE student_contacts 
            SET preferred_phone_number = '+263711206287',
                guardian_mobile_number = '+263711206287'
            WHERE student_id = 'SSC20247124'
        """))
        results.append("✅ SSC20247124 updated with +263711206287")
        
        # Update SSC20257279 - remove +263711206287  
        conn.execute(text("""
            UPDATE student_contacts 
            SET preferred_phone_number = NULL,
                guardian_mobile_number = NULL
            WHERE student_id = 'SSC20257279'
        """))
        results.append("✅ SSC20257279 cleared")
        
        conn.commit()
        
        # Verify changes
        query_result = conn.execute(text("""
            SELECT student_id, firstname, lastname, guardian_mobile_number, preferred_phone_number
            FROM student_contacts 
            WHERE student_id IN ('SSC20257279', 'SSC20247124')
        """))
        results.append("--- After Update ---")
        for row in query_result:
            results.append(str(row))
    
    return {
        'statusCode': 200,
        'body': json.dumps(results, indent=2)
    }
