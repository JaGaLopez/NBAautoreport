import hmac
import hashlib
import os
import subprocess
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
SCRIPT = os.environ.get("UPDATE_SCRIPT", "/repo/scripts/update.sh")


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Hub-Signature-256", "")
    body = await request.body()

    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid signature")

    subprocess.Popen(["bash", SCRIPT])
    return {"status": "update triggered"}
