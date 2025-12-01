#!/bin/bash
set -e

echo "🐳 DOCKER-BASED DEPLOYMENT - Linux-Compatible Packages"

REGION="us-east-2"
FUNCTION_NAME="shining-smiles-whatsapp"

# Clean up
rm -rf docker-package final-deployment.zip

echo "📦 Building packages in Docker (Linux environment)..."

# Use Lambda's base image to build packages
docker run --rm \
    --entrypoint /bin/bash \
    -v "$PWD":/var/task \
    -w /var/task \
    public.ecr.aws/lambda/python:3.11 \
    -c "
        mkdir -p docker-package
        cp -r src/* docker-package/
        cd docker-package
        pip install \
            requests==2.32.3 \
            sqlalchemy==2.0.31 \
            fpdf2==2.7.9 \
            Pillow==10.0.0 \
            segno==1.6.1 \
            pg8000==1.31.2 \
            openai==0.28.1 \
            ratelimit==2.2.1 \
            -t . --no-cache-dir
        echo '=== Verifying installed packages ==='
        ls -la | grep -E '(fpdf|pillow|segno|requests)' || echo 'No packages found!'
    "

echo "✅ Packages built successfully"

# Check if fpdf2 directory exists
if [ -d "docker-package/fpdf" ]; then
    echo "✅ fpdf2 installed"
else
    echo "❌ fpdf2 NOT found!"
    exit 1
fi

# Create deployment package
cd docker-package
zip -r ../final-deployment.zip . > /dev/null
cd ..

echo "📊 Package size: $(du -h final-deployment.zip | cut -f1)"

# Deploy
echo "⏱️  Updating Lambda timeout to 60 seconds..."
aws lambda update-function-configuration \
    --function-name $FUNCTION_NAME \
    --timeout 60 \
    --region $REGION

echo "⏳ Waiting for configuration update..."
aws lambda wait function-updated --function-name $FUNCTION_NAME --region $REGION

echo "🚀 Deploying to Lambda..."
aws lambda update-function-code \
    --function-name $FUNCTION_NAME \
    --zip-file fileb://final-deployment.zip \
    --region $REGION

aws lambda wait function-updated --function-name $FUNCTION_NAME --region $REGION

echo "🎉 DEPLOYMENT COMPLETE!"
echo ""
echo "✅ All packages built in Linux environment"
echo "✅ Pillow will work correctly on Lambda"

# Clean up
rm -rf docker-package final-deployment.zip