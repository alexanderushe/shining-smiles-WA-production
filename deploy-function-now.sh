#!/bin/bash
# deploy-function-only.sh - Update function code only, skip layer

set -e

echo "🚀 FUNCTION-ONLY DEPLOY: Skipping layer deployment..."

# Get current layer version
CURRENT_LAYER=$(aws lambda get-function --function-name shining-smiles-webhook --region us-east-2 --query 'Configuration.Layers[0].Arn' --output text)
echo "📋 Using existing layer: $CURRENT_LAYER"

# Clean and build function code only
rm -rf code-update.zip
cd src/

echo "🧹 Cleaning source code..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete

# Remove any packages that might have been accidentally installed
find . -maxdepth 1 -type d \( -name "twilio*" -o -name "openai*" -o -name "sqlalchemy*" -o -name "requests*" -o -name "flask*" -o -name "boto3*" \) -exec rm -rf {} + 2>/dev/null || true
rm -rf *.dist-info *.egg-info

echo "📦 Packaging function code..."
# Only include your source files
zip -r ../code-update.zip . \
    -x "*.pyc" "__pycache__/*" "*.dist-info" "*.egg-info" \
    "twilio*" "openai*" "sqlalchemy*" "requests*" "flask*" "boto3*" \
    "pillow*" "cryptography*" "reportlab*" "qrcode*" "pg8000*"

cd ..

echo "📡 Updating function code..."
aws lambda update-function-code \
    --function-name shining-smiles-webhook \
    --zip-file fileb://code-update.zip \
    --region us-east-2

echo "✅ Function code updated!"

# Wait for update
sleep 5

echo "🧪 Testing function..."
aws lambda invoke \
    --function-name shining-smiles-webhook \
    --payload '{"httpMethod":"GET","queryStringParameters":{"hub.mode":"subscribe","hub.verify_token":"shiningsmiles_verify_2025","hub.challenge":"test123"}}' \
    /tmp/test-response.json \
    --region us-east-2

echo "📋 Response:"
cat /tmp/test-response.json
echo ""

# Cleanup
rm -f code-update.zip /tmp/test-response.json

echo "🎉 Function-only deployment completed!"
echo "💡 Layer deployment skipped due to connection issues"
echo "📊 Using layer: $CURRENT_LAYER"
