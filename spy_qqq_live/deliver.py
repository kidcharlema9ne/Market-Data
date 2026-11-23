import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests

http = requests.Session()

def deliver(item):
    title, body = item["title"],item["body"]
    if item["channel"]=="push":
        r=http.post("https://api.pushover.net/1/messages.json",data={"token":os.environ["PUSHOVER_TOKEN"],"user":os.environ["PUSHOVER_USER"],"title":title,"message":body},timeout=20)
        r.raise_for_status()
        if r.json()["status"]!=1:
            raise RuntimeError("Pushover rejected message")
    else:
        if all(os.environ.get(k) for k in ("SPYQQQ_GMAIL_ADDRESS", "SPYQQQ_GMAIL_APP_PASSWORD", "SPYQQQ_EMAIL_TO")):
            msg = EmailMessage()
            msg["From"] = f'SPY/QQQ Trading System <{os.environ["SPYQQQ_GMAIL_ADDRESS"]}>'
            msg["To"] = os.environ["SPYQQQ_EMAIL_TO"]
            msg["Subject"] = title
            msg.set_content(body)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25) as smtp:
                smtp.login(os.environ["SPYQQQ_GMAIL_ADDRESS"], os.environ["SPYQQQ_GMAIL_APP_PASSWORD"])
                smtp.send_message(msg)
            print(f"Gmail SMTP accepted: {title}", flush=True)
            return
        raise RuntimeError("Missing Gmail configuration")

receipts = Path("spy_qqq_live/delivery_receipts.json")
sent = set(json.loads(receipts.read_text()) if receipts.exists() else [])
state = json.loads(Path(os.environ["SYSTEM_STATE"]).read_text())
pending = [(key, item) for key, item in state.get("outbox", {}).items() if key not in sent]
print(f"Notifications awaiting delivery: {len(pending)}", flush=True)
errors = []
for key, item in pending:
    try:
        deliver(item)
        sent.add(key)
        receipts.write_text(json.dumps(sorted(sent), indent=2) + "\n")
        print("Accepted", key, flush=True)
    except Exception as exc:
        errors.append(f"{key} {type(exc).__name__}")
if errors:
    raise SystemExit(" | ".join(errors))
