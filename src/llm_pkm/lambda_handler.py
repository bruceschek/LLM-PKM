"""Sketch of the future AWS Lambda entry point (API Gateway / function URL).
Not deployed or tested yet.

Request body:  {"message": "...", "history": [...optional prior messages...]}
Response body: {"reply": "...", "history": [...]}

The client holds the conversation history; memory itself lives in the store.
Settings come from Lambda environment variables (secrets should come from
Secrets Manager or SSM rather than plain env vars), and PKM_DATA_DIR must
point at /tmp or, better, the raw log should move to S3.
"""

import json

from .core import Assistant

_assistant: Assistant | None = None  # reused across warm invocations


def handler(event: dict, context) -> dict:
    global _assistant
    if _assistant is None:
        _assistant = Assistant.from_env()
    body = json.loads(event.get("body") or "{}")
    history = body.get("history", [])
    reply = _assistant.handle_message(body["message"], history)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"reply": reply, "history": history}),
    }
