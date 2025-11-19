#!/bin/bash
# deploy-layer.sh - Build and deploy Lambda layer

set -e  # Exit on error

echo "🚀 Building and deploying Lambda layer..."

# Clean and rebuild layer
rm -rf layer-build/python
mkdir -p layer-build/python/lib/python3.11/site-packages

cd layer-build

echo "📦 Installing dependencies..."
pip install \
  twilio==9.3.0 \
  openai==1.44.1 \
  sqlalchemy==2.0.31 \
  psycopg2-binary==2.9.9 \
  pg8000==1.31.2 \
  requests==2.32.3 \
  flask==3.0.3 \
  boto3==1.35.39 \
  python-dotenv==1.0.1 \
  qrcode==8.2 \
  pillow==11.2.1 \
  pyjwt==2.10.1 \
  cryptography==45.0.5 \
  ratelimit==2.2.1 \
  reportlab==4.2.0 \
  -t python/lib/python3.11/site-packages/ --no-cache-dir

# Verify key packages are installed
echo "🔍 Verifying key packages..."
ls python/lib/python3.11/site-packages/ | grep -E "pg8000|reportlab" || echo "❌ Some packages not found!"

echo "✅ Dependencies installed"

# Create ZIP
echo "📦 Creating ZIP file..."
zip -r aws-sam-python3.11-layer.zip python/
cd ..

# Check ZIP size
echo "📊 ZIP file size:"
ls -lh layer-build/aws-sam-python3.11-layer.zip

# Deploy layer with retry logic
echo "📡 Deploying layer..."
MAX_RETRIES=3
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    LAYER_RESULT=$(aws lambda publish-layer-version \
        --layer-name shining-smiles-deps-layer \
        --description "Complete dependencies including pg8000 and reportlab" \
        --zip-file fileb://layer-build/aws-sam-python3.11-layer.zip \
        --compatible-runtimes python3.11 \
        --region us-east-2 \
        --output json 2>/dev/null) && break
    
    RETRY_COUNT=$((RETRY_COUNT+1))
    echo "❌ Deployment failed, retry $RETRY_COUNT/$MAX_RETRIES in 10 seconds..."
    sleep 10
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ Failed to deploy layer after $MAX_RETRIES attempts"
    exit 1
fi

# Extract the new layer ARN and version
NEW_LAYER_ARN=$(echo $LAYER_RESULT | jq -r '.LayerVersionArn')
NEW_LAYER_VERSION=$(echo $LAYER_RESULT | jq -r '.Version')

echo "🎉 Layer deployed successfully!"
echo "📋 New Layer ARN: $NEW_LAYER_ARN"
echo "🔢 New Layer Version: $NEW_LAYER_VERSION"

# Store the new layer version
echo "$NEW_LAYER_ARN" > .current-layer-arn
echo "$NEW_LAYER_VERSION" > .current-layer-version