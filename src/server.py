"""WSGI entry — run the WhatsApp bot as a long-lived container (Hetzner) instead
of AWS Lambda.

Wraps the inbound Meta webhook HTTP request into the API-Gateway-style event dict
that ``webhook_handler.lambda_handler(event, context)`` already expects, so ALL
existing bot logic is reused unchanged. Served by gunicorn.

Scheduled jobs (payment-check, reminders) move to systemd timers that call
``lambda_handler({"source": "aws.events", "action": ...}, None)`` — not this app.
"""
import json
import types

from flask import Flask, Response, request

from webhook_handler import lambda_handler
from routes.verify import verify_bp
from routes.receipts import receipts_bp

app = Flask(__name__)
app.register_blueprint(verify_bp)
app.register_blueprint(receipts_bp)

# Minimal stand-in for the Lambda context. The live webhook path doesn't use it;
# only the retired self-invoke recursion did (now a no-op).
_CTX = types.SimpleNamespace(function_name="shining-smiles-bot", aws_request_id="container")


@app.get("/healthz")
def healthz():
    return "ok", 200


@app.route("/webhook", methods=["GET", "POST"])
@app.route("/", methods=["GET", "POST"])
def webhook():
    event = {
        "httpMethod": request.method,
        "rawPath": request.path,
        "queryStringParameters": dict(request.args),
        "headers": {k: v for k, v in request.headers.items()},
        "body": request.get_data(as_text=True),
        "isBase64Encoded": False,
    }
    result = lambda_handler(event, _CTX) or {}
    body = result.get("body", "")
    if not isinstance(body, str):
        body = json.dumps(body)
    return Response(
        body,
        status=result.get("statusCode", 200),
        headers=result.get("headers", {}),
    )
