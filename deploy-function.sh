#!/bin/bash
# deploy-function.sh - Deploy function code to existing shining-smiles-webhook

set -e  # Exit on error

echo "🚀 Deploying function code to shining-smiles-webhook..."

# Check if we have a current layer version
if [ ! -f .current-layer-arn ]; then
    echo "❌ No current layer version found. Run deploy-layer.sh first."
    exit 1
fi

CURRENT_LAYER_ARN=$(cat .current-layer-arn)
CURRENT_LAYER_VERSION=$(cat .current-layer-version)

echo "📋 Using layer: $CURRENT_LAYER_ARN"

# Clean build artifacts
rm -rf .aws-sam build code-update.zip

# Clean src/ directory (remove installed packages but keep data/)
cd src/
echo "🧹 Cleaning src/ directory..."
# Remove only Python packages, keep data and your code
rm -rf __pycache__ *.pyc *.dist-info *.egg-info twilio* openai* sqlalchemy* psycopg2* requests* flask* boto3* python_dotenv* qrcode* Pillow* pyjwt* cryptography* ratelimit* pg8000*

echo "📦 Creating deployment package..."
# Make sure data directory and all Python files are included
zip -r ../code-update.zip . -x "*.pyc" "__pycache__/*"
cd ..

echo "📡 Updating Lambda function: shining-smiles-webhook"
aws lambda update-function-code \
    --function-name shining-smiles-webhook \
    --zip-file fileb://code-update.zip \
    --region us-east-2

echo "🔄 Updating function configuration with layer..."
aws lambda update-function-configuration \
    --function-name shining-smiles-webhook \
    --layers "$CURRENT_LAYER_ARN" \
    --region us-east-2

echo "✅ Function code and layer configuration deployed successfully!"

# Wait for update to complete
echo "⏳ Waiting for function update to complete..."
sleep 10

echo "🧪 Testing function with webhook verification..."
# Create a proper test payload file
cat > test-payload.json << 'EOF'
{
  "httpMethod": "GET",
  "queryStringParameters": {
    "hub.mode": "subscribe",
    "hub.verify_token": "shiningsmiles_verify_2025", 
    "hub.challenge": "test_123"
  }
}
EOF

aws lambda invoke \
    --function-name shining-smiles-webhook \
    --payload fileb://test-payload.json \
    response.json \
    --region us-east-2

echo "📋 Test response:"
cat response.json

# Clean up test file
rm -f test-payload.json response.json

# Verify the update
echo "🔍 Verifying deployment..."
aws lambda get-function \
    --function-name shining-smiles-webhook \
    --region us-east-2 \
    --query 'Configuration.{FunctionName:FunctionName, LastModified:LastModified, Layers:Layers[].Arn}' \
    --output table