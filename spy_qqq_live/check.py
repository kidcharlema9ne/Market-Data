"""Verified SPY/QQQ end-of-day signals. Called only by workflow_dispatch."""
import json
import smtplib
from email.message import EmailMessage
import os
import subprocess
import time
from datetime import datetime, timedelta
from decimal import Decimal as D
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import pandas as pd
import requests

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent
PATH = ROOT / "state.json"
state = json.loads(PATH.read_text())
http = requests.Session()
http.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
calendar = xc.get_calendar("XNYS")
now = datetime.now(NY)
today = now.date().isoformat()
mode = os.environ["CHECK_MODE"]


def get(url, **kwargs):
    res = http.get(url, timeout=20, **kwargs)
    res.raise_for_status()
    return res


def yahoo(t):
    data = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}", params={"range":"6mo","interval":"1d"}).json()["chart"]["result"][0]
    return {datetime.fromtimestamp(stamp, NY).date().isoformat(): price for stamp, price in zip(data["timestamp"], data["indicators"]["quote"][0]["close"]) if price}


def stock_analysis(t):
    table = pd.read_html(StringIO(get(f"https://stockanalysis.com/etf/{t.lower()}/history/").text))[0]
    return {pd.Timestamp(row["Date"]).date().isoformat():row["Close"] for _,row in table.iterrows() if pd.notna(row["Close"])}


def nasdaq(t):
    rows = get(f"https://api.nasdaq.com/api/quote/{t}/historical", params={"assetclass":"etf","fromdate":state["date"],"todate":today,"limit":250},headers={"Accept":"application/json","Referer":"https://www.nasdaq.com/"}).json()["data"]["tradesTable"]["rows"]
    return {pd.Timestamp(r["date"]).date().isoformat():r["close"].replace("$","").replace(",","") for r in rows}


def stooq(t):
    response = get("https://stooq.com/q/l/", params={
        "s": t.lower() + ".us", "f": "sd2t2ohlc", "h": "", "e": "csv"})
    row = pd.read_csv(StringIO(response.text)).iloc[0]
    day = pd.Timestamp(row["Date"]).date().isoformat()
    if day == today and datetime.now(NY) < calendar.session_close(day).to_pydatetime() + timedelta(minutes=20):
        return {}
    return {day: float(row["Close"])}


def twelve_data(t):
    market_id = {"SPY": "568728/etf/nyse", "QQQ": "958673/etf/nasdaq"}[t]
    url = f"https://twelvedata.com/markets/{market_id}/{t.lower()}/historical-data"
    response = get(url)
    if t.lower() not in response.url.lower().split("/"):
        return {}
    table = next((table for table in pd.read_html(StringIO(response.text))
                  if {"Date", "Close"} <= set(table.columns)), None)
    if table is None:
        return {}
    return {pd.Timestamp(row["Date"]).date().isoformat(): row["Close"] for _, row in table.iterrows()}


def fetch(source,t):
    try:
        return source(t)
    except (ValueError, TypeError, KeyError, IndexError, requests.RequestException) as error:
        print(t, source.__name__,type(error).__name__)
        return {}


def queue(key, channels, title, body):
    for channel in channels:
        state.setdefault("pending",{}).setdefault(key+"-"+channel, dict(channel=channel,title=title,body=body))


def closing_minute(t):
    data = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{t}",
               params={"range": "5d", "interval": "1m", "includePrePost": "false"}).json()["chart"]["result"][0]
    result = {}
    for stamp, price in zip(data["timestamp"], data["indicators"]["quote"][0]["close"]):
        if price is None:
            continue
        instant = pd.Timestamp(stamp, unit="s", tz="UTC")
        day = instant.tz_convert(NY).date().isoformat()
        if instant + pd.Timedelta(minutes=1) == calendar.session_close(day):
            result[day] = price
    return result


def check():
    dates = state.setdefault("symbol_dates", {t: state["date"] for t in state["state"]})
    problems = []
    for t, last in dates.copy().items():
        if last >= today:
            continue
        days = calendar.sessions_in_range(pd.Timestamp(last) + pd.Timedelta(days=1), today)
        days = [s.date().isoformat() for s in days if calendar.session_close(s).to_pydatetime() <= datetime.now(NY)]
        if not days:
            continue
        feeds = {}
        for day in days:
            history = state["prices"][t]
            subtotal = sum(D(str(v)) for v in history[1:])
            old = state["state"][t]
            def position(p):
                avg = (subtotal + p) / 200
                return p > avg * D("1.03") if not old else p >= avg * D(".97")
            quotes = {}
            for source in (stock_analysis, nasdaq, yahoo, closing_minute, stooq, twelve_data):
                provider = "yahoo" if source is closing_minute else source.__name__
                if provider in quotes:
                    continue
                if source not in feeds:
                    feeds[source] = fetch(source, t)
                raw = feeds[source].get(day)
                if raw is None:
                    continue
                p = D(str(raw))
                if not p.is_finite() or p <= 0:
                    continue
                quotes[provider] = p.quantize(D(".01"))
                matches = [(name, other) for name, other in quotes.items() if name != provider
                           and abs(other - p) <= min(other, p) * D(".0005")
                           and position(other) == position(p)]
                if matches:
                    first_name, first_price = matches[0]
                    source_names = f"{first_name} {first_price}, {provider} {quotes[provider]}"
                    p = first_price
                    break
            else:
                problems.append(f"{day} {t}: awaiting two corroborating closing prices ({quotes})")
                break
            history[:] = history[1:] + [float(p)]
            avg = (subtotal + p) / 200
            new = position(p)
            dates[t] = day
            state["state"][t] = new
            print(f"{day} {t} {p} ({source_names}) SMA {avg:.2f} LONG={new}", flush=True)
            if new != old and day >= "2026-11-20":
                side = "BUY" if new else "SELL"
                execution = calendar.next_session(day).date()
                queue(day+t, ["email", "push"],
                      f"TRADE ALERT | {side} {t} | {day}",
                      f"{side} {t}\nRegular-session price: {p} ({source_names})\n200-session SMA: {avg:.2f}\nBands: {avg*D('.97'):.2f} to {avg*D('1.03'):.2f}\nResearch execution: {execution} close.")
    state["date"] = min(dates.values())
    if problems:
        raise ValueError(" | ".join(problems))


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
        if "TRADE ALERT" in title:
            raise RuntimeError("Missing Gmail configuration for trade alert")
        matches = subprocess.check_output(
            ["gh", "issue", "list", "--state", "all", "--search", f'"{title}" in:title',
             "--json", "title"], text=True)
        if any(issue["title"] == title for issue in json.loads(matches)):
            return
        owner = os.environ["GITHUB_REPOSITORY_OWNER"]
        subprocess.run(["gh", "issue", "create", "--title", title, "--body-file", "-"],
                       input=f"@{owner}\n\n" + body.replace("\n", "  \n"),
                       text=True, check=True)


if mode == "test":
    positions = "\n".join(t + ": " + ("LONG" if v else "FLAT") for t, v in state["state"].items())
    for channel in ("email", "push"):
        deliver({"channel":channel, "title":f"TEST | SPY/QQQ STATUS ALERT | {today} | {os.environ['GITHUB_RUN_ID']}",
                 "body":f"Delivery test. Verified through {state['date']}.\n{positions}"})
    raise SystemExit(0)

errors=[]
for attempt in range(3):
    try:
        check()
        break
    except ValueError as exc:
        if attempt==2:
            errors.append(str(exc))
        else:
            time.sleep(75)
if errors and state.get("warned_on") != today:
    queue(today+"data", ["push"], f"SPY/QQQ DATA DELAY | {today}", "Signal check incomplete. " + " | ".join(errors))
    state["warned_on"] = today
if mode in ("daily", "weekly"):
    state.setdefault("daily_runs",{})[today]={"through":state["date"],"errors":errors.copy()}
if mode=="weekly" and now.weekday()==0 and state.get("weekly_queued")!=today:
    since=(now.date()-timedelta(days=6)).isoformat()
    days=[s.date().isoformat() for s in calendar.sessions_in_range(max(since,"2026-11-20"),today)]
    missed=[d for d in days if state.get("daily_runs",{}).get(d,{}).get("through")!=d]
    positions="\n".join(t+": "+("LONG" if v else "FLAT") for t,v in state["state"].items())
    body=f"Verified through {state['date']}\n{positions}\nMissing or incomplete daily runs: {', '.join(missed) or 'none'}\nPending prior deliveries: {len(state.get('pending',{}))}\nPrice errors: {', '.join(errors) or 'none'}"
    queue(today+"status",["email","push"],f"SPY/QQQ STATUS ALERT | {today}",body)
    state["weekly_queued"]=today
for key,item in list(state.get("pending",{}).items()):
    try:
        deliver(item)
        del state["pending"][key]
    except Exception as exc:
        errors.append(key+" "+type(exc).__name__)
PATH.write_text(json.dumps(state,indent=2)+"\n")
if errors:
    raise SystemExit(" | ".join(errors))
