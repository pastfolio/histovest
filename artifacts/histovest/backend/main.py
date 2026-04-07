import os
import random
import math
from datetime import datetime, timedelta
from typing import Literal

import yfinance as yf
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="HistoVest API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SP500_TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JNJ", "JPM", "XOM",
    "V", "PG", "UNH", "MA", "HD", "CVX", "MRK", "LLY", "ABBV", "PEP", "KO",
    "BAC", "AVGO", "MCD", "PFE", "COST", "TMO", "ABT", "ACN", "WMT", "DIS",
    "CSCO", "DHR", "VZ", "ADBE", "CRM", "NEE", "NKE", "TXN", "AMD", "INTC",
    "QCOM", "HON", "PM", "IBM", "GE", "BA", "CAT", "MMM", "GS", "MS",
    "WFC", "C", "USB", "AXP", "BK", "SCHW", "CB", "MET", "PRU", "TRV",
    "UPS", "FDX", "LMT", "RTX", "GD", "NOC", "DE", "EMR", "ETN", "ITW",
    "SHW", "ECL", "APD", "PPG", "LIN", "DOW", "DD", "NUE", "FCX", "ALB",
    "CVS", "WBA", "MCK", "ABC", "CAH", "HCA", "UHS", "CNC", "HUM", "CI",
    "T", "CMCSA", "CHTR", "TMUS", "ATVI", "EA", "TTWO", "NFLX", "PARA",
    "F", "GM", "TM", "HMC", "DAL", "UAL", "AAL", "LUV", "MAR", "HLT",
    "LOW", "TGT", "KR", "SYY", "YUM", "MCD", "CMG", "DRI", "SBUX",
    "CL", "CHD", "CLX", "EL", "KMB", "MO", "STZ", "TAP", "ADM", "BG",
    "ETR", "EXC", "DUK", "SO", "AEP", "D", "PEG", "ED", "EIX", "XEL",
    "AMT", "CCI", "EQIX", "PLD", "PSA", "AVB", "EQR", "SPG", "O", "VTR",
]

SP500_TICKERS = list(set(SP500_TICKERS))


def pick_random_window():
    start_year = random.randint(1995, 2017)
    start_month = random.randint(1, 12)
    start_date = datetime(start_year, start_month, 1)
    reveal_start = start_date + timedelta(days=365)
    end_date = reveal_start + timedelta(days=185)
    if end_date.year > 2018:
        end_date = datetime(2018, 12, 31)
        reveal_start = end_date - timedelta(days=185)
        start_date = reveal_start - timedelta(days=365)
    return start_date, reveal_start, end_date


def ohlcv_to_json(df: pd.DataFrame) -> list:
    result = []
    for ts, row in df.iterrows():
        if hasattr(ts, 'timestamp'):
            unix_ts = int(ts.timestamp())
        else:
            unix_ts = int(pd.Timestamp(ts).timestamp())

        o = float(row.get("Open", row.get("open", 0)))
        h = float(row.get("High", row.get("high", 0)))
        l = float(row.get("Low", row.get("low", 0)))
        c = float(row.get("Close", row.get("close", 0)))
        v = float(row.get("Volume", row.get("volume", 0)))

        if any(math.isnan(x) for x in [o, h, l, c]):
            continue

        result.append({
            "time": unix_ts,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": int(v) if not math.isnan(v) else 0,
        })
    return result


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def get_fundamentals(stock: yf.Ticker, start_date: datetime, start_price: float) -> dict:
    result = {"pe_ratio": None, "sector": None, "market_cap_category": None}

    # ── Sector from info ────────────────────────────────────────────────────
    try:
        info = stock.info
        sector = info.get("sector") or info.get("sectorDisp")
        if sector:
            result["sector"] = sector
    except Exception as e:
        print(f"Sector error: {e}")

    # ── Income statement → EPS → P/E ───────────────────────────────────────
    try:
        for attr in ("income_stmt", "financials"):
            stmt = getattr(stock, attr, None)
            if stmt is None or stmt.empty:
                continue
            cols = [(pd.Timestamp(c), c) for c in stmt.columns]
            before = [(ts, c) for ts, c in cols if ts <= pd.Timestamp(start_date)]
            if not before:
                continue
            _, best_col = max(before, key=lambda x: x[0])
            for row_name in ("Basic EPS", "Diluted EPS"):
                if row_name in stmt.index:
                    eps_val = stmt.loc[row_name, best_col]
                    if eps_val is not None:
                        eps = float(eps_val)
                        if not math.isnan(eps) and eps > 0:
                            result["pe_ratio"] = round(start_price / eps, 1)
                            break
            if result["pe_ratio"] is not None:
                break
    except Exception as e:
        print(f"P/E error: {e}")

    # ── Historical market cap → size category ──────────────────────────────
    def cap_category(mkt_cap: float) -> str:
        if mkt_cap >= 200e9:  return "Mega Cap"
        if mkt_cap >= 10e9:   return "Large Cap"
        if mkt_cap >= 2e9:    return "Mid Cap"
        if mkt_cap >= 300e6:  return "Small Cap"
        return "Micro Cap"

    try:
        shares = None
        for attr in ("balance_sheet", "quarterly_balance_sheet"):
            bs = getattr(stock, attr, None)
            if bs is None or bs.empty:
                continue
            cols = [(pd.Timestamp(c), c) for c in bs.columns]
            before = [(ts, c) for ts, c in cols if ts <= pd.Timestamp(start_date)]
            if not before:
                before = [(pd.Timestamp(c), c) for c in bs.columns]
            if not before:
                continue
            _, best_col = max(before, key=lambda x: x[0])
            for row_name in (
                "Ordinary Shares Number",
                "Share Issued",
                "Common Stock Shares Outstanding",
                "Diluted Average Shares",
            ):
                if row_name in bs.index:
                    v = bs.loc[row_name, best_col]
                    if v is not None:
                        try:
                            fv = float(v)
                            if not math.isnan(fv) and fv > 0:
                                shares = fv
                                break
                        except (TypeError, ValueError):
                            pass
            if shares:
                break

        if shares:
            result["market_cap_category"] = cap_category(shares * start_price)
        else:
            # fall back to current market cap from info (already fetched for sector)
            try:
                mc = stock.info.get("marketCap")
                if mc and mc > 0:
                    result["market_cap_category"] = cap_category(float(mc))
            except Exception:
                pass
    except Exception as e:
        print(f"Market cap error: {e}")

    return result


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path, "r") as f:
        content = f.read()
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.get("/challenge")
def get_challenge():
    attempts = 0
    while attempts < 20:
        attempts += 1
        ticker = random.choice(SP500_TICKERS)
        start_date, reveal_start, end_date = pick_random_window()

        fetch_start = (start_date - timedelta(days=5)).strftime("%Y-%m-%d")
        fetch_end = (end_date + timedelta(days=5)).strftime("%Y-%m-%d")

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=fetch_start, end=fetch_end, auto_adjust=True)

            if df.empty or len(df) < 50:
                continue

            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index

            challenge_df = df[df.index < reveal_start]
            reveal_df = df[df.index >= reveal_start]

            if len(challenge_df) < 30 or len(reveal_df) < 5:
                continue

            spx = yf.Ticker("^GSPC")
            spx_df = spx.history(start=fetch_start, end=fetch_end, auto_adjust=True)

            if spx_df.empty:
                continue

            spx_df.index = pd.to_datetime(spx_df.index)
            spx_df = spx_df.sort_index()
            spx_df.index = spx_df.index.tz_localize(None) if spx_df.index.tzinfo else spx_df.index

            spx_challenge = spx_df[spx_df.index < reveal_start]
            spx_reveal = spx_df[spx_df.index >= reveal_start]

            challenge_json = ohlcv_to_json(challenge_df)
            reveal_json = ohlcv_to_json(reveal_df)
            spx_challenge_json = ohlcv_to_json(spx_challenge)
            spx_reveal_json = ohlcv_to_json(spx_reveal)

            if not challenge_json or not reveal_json:
                continue

            stock_start_price = challenge_json[0]["close"]
            stock_end_price = challenge_json[-1]["close"]
            stock_reveal_end_price = reveal_json[-1]["close"]

            spx_reveal_start = spx_reveal_json[0]["close"] if spx_reveal_json else None
            spx_reveal_end = spx_reveal_json[-1]["close"] if spx_reveal_json else None

            if spx_reveal_start and spx_reveal_end and spx_reveal_start > 0:
                spx_return_pct = round((spx_reveal_end - spx_reveal_start) / spx_reveal_start * 100, 2)
            else:
                spx_return_pct = None

            try:
                info = stock.info
                company_name = info.get("longName") or info.get("shortName") or ticker
            except Exception:
                company_name = ticker

            fundamentals = get_fundamentals(stock, start_date, stock_start_price)

            return {
                "challenge": challenge_json,
                "reveal": reveal_json,
                "spx_challenge": spx_challenge_json,
                "spx_reveal": spx_reveal_json,
                "meta": {
                    "stock_start_price": round(stock_start_price, 4),
                    "stock_end_price": round(stock_end_price, 4),
                    "stock_reveal_end_price": round(stock_reveal_end_price, 4),
                    "spx_return_pct": spx_return_pct,
                    "challenge_candles": len(challenge_json),
                    "reveal_candles": len(reveal_json),
                    "ticker": ticker,
                    "company_name": company_name,
                    "challenge_year": start_date.year,
                },
                "fundamentals": fundamentals,
            }

        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            continue

    raise HTTPException(status_code=503, detail="Could not fetch stock data after multiple attempts")


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
