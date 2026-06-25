#!/usr/bin/env bash
#
# deploy-bot.sh — build + (re)deploy the WhatsApp bot container to a box.
#
# Ships the build context (src/ + requirements.txt + Dockerfile.server + templates/)
# to the target box, rebuilds the image there, recreates the container with the
# box's existing /…/.env.bot, and verifies /healthz. The env file on the box is
# the source of truth for secrets — this script never touches it.
#
# Usage:
#   ./deploy-bot.sh staging      # 167.233.206.105  -> wa-bot-staging
#   ./deploy-bot.sh prod         # 78.47.178.15     -> wa-bot   (prompts to confirm)
#
# Env overrides: SSH_KEY (default ~/.ssh/id_ed25519)
set -euo pipefail

TARGET="${1:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$TARGET" in
  staging)
    BOX=167.233.206.105
    DIR=/opt/wa-bot-staging
    NAME=wa-bot-staging
    IMG=wa-bot:staging
    NET=ongororo-staging-network
    PORT=8092
    ;;
  prod)
    BOX=78.47.178.15
    DIR=/opt/wa-bot
    NAME=wa-bot
    IMG=wa-bot:prod
    NET=ongororo_ongororo-network
    PORT=8091
    ;;
  *)
    echo "Usage: $0 staging|prod" >&2
    exit 1
    ;;
esac

ENV_FILE="$DIR/.env.bot"
SSH="ssh -o BatchMode=yes -o ServerAliveInterval=30 -i $SSH_KEY root@$BOX"

# Prod is live — make the operator confirm.
if [ "$TARGET" = "prod" ]; then
  read -r -p "⚠️  Deploy to PRODUCTION ($NAME on $BOX)? Type 'yes': " ok
  [ "$ok" = "yes" ] || { echo "aborted"; exit 1; }
fi

echo ">> [$TARGET] shipping build context to $BOX:$DIR"
$SSH "mkdir -p $DIR"
COPYFILE_DISABLE=1 tar czf - -C "$SCRIPT_DIR" src requirements.txt Dockerfile.server templates static 2>/dev/null \
  | $SSH "tar xzf - -C $DIR"

echo ">> [$TARGET] verifying env file exists on box"
$SSH "test -f $ENV_FILE" || { echo "ERROR: $ENV_FILE missing on $BOX — create it first" >&2; exit 1; }

echo ">> [$TARGET] building image $IMG"
$SSH "cd $DIR && docker build -f Dockerfile.server -t $IMG . >/tmp/wa-build.log 2>&1" \
  || { echo 'BUILD FAILED:'; $SSH 'tail -20 /tmp/wa-build.log'; exit 1; }

echo ">> [$TARGET] recreating container $NAME"
$SSH "docker rm -f $NAME >/dev/null 2>&1 || true; \
      docker run -d --name $NAME --restart unless-stopped \
        --network $NET -p 127.0.0.1:$PORT:8080 \
        --env-file $ENV_FILE $IMG >/dev/null"

echo ">> [$TARGET] waiting for healthz"
for i in $(seq 1 10); do
  sleep 2
  code=$($SSH "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/healthz" || echo 000)
  if [ "$code" = "200" ]; then
    echo ">> OK: $NAME healthy on $BOX (attempt $i)"
    exit 0
  fi
done

echo "ERROR: $NAME did not become healthy — recent logs:" >&2
$SSH "docker logs --tail 30 $NAME"
exit 1
