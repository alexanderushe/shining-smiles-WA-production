#!/bin/bash
set -e

echo "🚀 SAM INFRASTRUCTURE DEPLOYMENT"
echo "This script deploys both the code and the infrastructure (EventBridge rules, API Gateway, etc.)"

STACK_NAME="shining-smiles-wa-production"
REGION="us-east-2"

# Build the application
echo "📦 Building with SAM (using Docker for compatibility)..."
sam build --use-container

# Deploy
echo "🚀 Deploying to AWS..."
sam deploy \
    --stack-name $STACK_NAME \
    --region $REGION \
    --capabilities CAPABILITY_IAM \
    --resolve-s3 \
    --no-confirm-changeset

echo "🎉 DEPLOYMENT COMPLETE!"
echo "✅ EventBridge rules and Lambda function updated."
