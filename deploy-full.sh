#!/bin/bash
# deploy-full.sh - Complete deployment (layer + function) to existing function

set -e  # Exit on error

echo "🚀 Starting full deployment to shining-smiles-webhook..."

# Deploy layer first
./deploy-layer.sh

# Wait a moment for layer to be available
sleep 5

# Deploy function
./deploy-function.sh

echo "🎉 Full deployment completed!"
echo "📊 Summary:"
echo "   - Layer updated to version $(cat .current-layer-version)"
echo "   - Function code deployed to shining-smiles-webhook"
echo "   - Function configured with layer $(cat .current-layer-arn)"