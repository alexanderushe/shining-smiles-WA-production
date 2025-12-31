#!/bin/bash
# CloudWatch Logs Monitoring Commands for JIT Testing

echo "=== CLOUDWATCH LOGS MONITORING COMMANDS ==="
echo ""

# Command 1: Tail live logs (shows new logs as they come in)
echo "📊 COMMAND 1: Watch logs in real-time"
echo "--------------------------------------"
cat << 'EOF'
aws logs tail /aws/lambda/shining-smiles-whatsapp \
  --follow \
  --format short \
  --region us-east-2
EOF
echo ""
echo "Use this WHILE testing - it shows logs as they happen"
echo ""

# Command 2: Search for JIT Sync messages (last 10 minutes)
echo "🔍 COMMAND 2: Search for JIT sync activity (last 10 min)"
echo "--------------------------------------"
cat << 'EOF'
aws logs filter-log-events \
  --log-group-name /aws/lambda/shining-smiles-whatsapp \
  --filter-pattern "[JIT Sync]" \
  --start-time $(($(date +%s) * 1000 - 600000)) \
  --region us-east-2 \
  --output text \
  --query 'events[*].[timestamp,message]'
EOF
echo ""

# Command 3: Get recent function invocations (last 5)
echo "📋 COMMAND 3: Show last 5 Lambda invocations"
echo "--------------------------------------"
cat << 'EOF'
aws logs tail /aws/lambda/shining-smiles-whatsapp \
  --since 10m \
  --format short \
  --region us-east-2 | head -100
EOF
echo ""

# Command 4: Search for specific student ID
echo "🎯 COMMAND 4: Search for specific student (replace SSC12345)"
echo "--------------------------------------"
cat << 'EOF'
aws logs filter-log-events \
  --log-group-name /aws/lambda/shining-smiles-whatsapp \
  --filter-pattern "SSC12345" \
  --start-time $(($(date +%s) * 1000 - 3600000)) \
  --region us-east-2 \
  --output text
EOF
echo ""

# Command 5: Count JIT sync attempts
echo "📈 COMMAND 5: Count JIT sync attempts today"
echo "--------------------------------------"
cat << 'EOF'
aws logs filter-log-events \
  --log-group-name /aws/lambda/shining-smiles-whatsapp \
  --filter-pattern "[JIT Sync]" \
  --start-time $(($(date +%s) * 1000 - 86400000)) \
  --region us-east-2 \
  --query 'length(events)' \
  --output text
EOF
echo ""

echo "=== TESTING WORKFLOW ==="
echo ""
echo "1. Open a terminal and run COMMAND 1 (tail logs)"
echo "2. In another window, trigger a WhatsApp gatepass request"
echo "3. Watch the logs appear in real-time"
echo "4. Look for [JIT Sync] messages"
echo ""
echo "=== SUCCESS INDICATORS ==="
echo ""
echo "✅ [INFO] Student SSCxxxxx not in local DB, attempting JIT sync"
echo "✅ [INFO] [JIT Sync] Fetching profile from SMS API for SSCxxxxx"
echo "✅ [INFO] [JIT Sync] Successfully created contact for SSCxxxxx"
echo "✅ [INFO] JIT sync successful for SSCxxxxx"
echo "✅ [INFO] Gate pass issued"
echo ""
