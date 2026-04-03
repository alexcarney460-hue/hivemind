#!/usr/bin/env python3
"""MEXC Futures Trading Client — direct API execution for Hivemind agents.

No browser. No Playwright. No screenshots. Pure HTTP.
Place orders, check positions, manage risk — all via REST API.

Usage as CLI:
  python3 mexc.py price ETH_USDT
  python3 mexc.py balance
  python3 mexc.py positions
  python3 mexc.py long ETH_USDT 100 8 --sl 1950 --tp 2200
  python3 mexc.py short ETH_USDT 100 8 --sl 2250 --tp 1800
  python3 mexc.py close ETH_USDT
  python3 mexc.py cancel [order_id]
  python3 mexc.py orders
  python3 mexc.py history 10

Usage as module:
  from mexc import MexcFutures
  client = MexcFutures()
  price = client.get_price("ETH_USDT")
  client.open_short("ETH_USDT", vol=100, leverage=8, stop_loss=2250, take_profit=1800)
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "https://contract.mexc.com"

# Load keys from environment or file
API_KEY = os.environ.get("MEXC_API_KEY", "mx0vglxjaZezZH98Oy")
API_SECRET = os.environ.get("MEXC_API_SECRET", "68afaf7098a941b586b9828106ce924a")


class MexcFutures:
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or API_KEY
        self.api_secret = api_secret or API_SECRET

    def _sign(self, timestamp, params_str=""):
        """HMAC-SHA256 signature: accessKey + timestamp + params"""
        sign_str = self.api_key + str(timestamp) + params_str
        return hmac.new(
            self.api_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest()

    def _request(self, method, path, params=None, body=None, signed=True):
        url = f"{BASE_URL}{path}"
        timestamp = int(time.time() * 1000)
        headers = {"Content-Type": "application/json"}

        if signed:
            if body:
                params_str = json.dumps(body, separators=(",", ":"))
            elif params:
                params_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            else:
                params_str = ""

            headers["ApiKey"] = self.api_key
            headers["Request-Time"] = str(timestamp)
            headers["Signature"] = self._sign(timestamp, params_str)

        if params and method == "GET":
            url += "?" + urllib.parse.urlencode(params)

        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if result.get("success") is False or result.get("code", 0) != 0:
                    return {"error": result.get("message", str(result)), "raw": result}
                return result
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ""
            return {"error": f"HTTP {e.code}: {body_text[:300]}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Market Data (no auth needed) ──

    def get_price(self, symbol):
        """Get current price for a symbol."""
        result = self._request("GET", "/api/v1/contract/ticker", {"symbol": symbol}, signed=False)
        if "error" in result:
            return result
        data = result.get("data", {})
        return {
            "symbol": symbol,
            "price": float(data.get("lastPrice", 0)),
            "bid": float(data.get("bid1", 0)),
            "ask": float(data.get("ask1", 0)),
            "high24h": float(data.get("high24Price", 0)),
            "low24h": float(data.get("lower24Price", 0)),
            "volume24h": float(data.get("volume24", 0)),
            "change24h": float(data.get("riseFallRate", 0)),
            "funding_rate": float(data.get("fundingRate", 0)),
        }

    def get_depth(self, symbol, limit=5):
        """Get order book."""
        result = self._request("GET", "/api/v1/contract/depth/{symbol}".format(symbol=symbol),
                               {"limit": limit}, signed=False)
        return result.get("data", result)

    def get_klines(self, symbol, interval="Min60", limit=20):
        """Get candlestick data."""
        result = self._request("GET", "/api/v1/contract/kline/{symbol}".format(symbol=symbol),
                               {"interval": interval, "limit": limit}, signed=False)
        return result.get("data", result)

    # ── Account (auth required) ──

    def get_balance(self):
        """Get futures account balance."""
        result = self._request("GET", "/api/v1/private/account/assets")
        if "error" in result:
            return result
        data = result.get("data", [])
        balances = []
        for asset in data:
            if float(asset.get("availableBalance", 0)) > 0 or float(asset.get("frozenBalance", 0)) > 0:
                balances.append({
                    "currency": asset.get("currency"),
                    "available": float(asset.get("availableBalance", 0)),
                    "frozen": float(asset.get("frozenBalance", 0)),
                    "equity": float(asset.get("equity", 0)),
                    "unrealized_pnl": float(asset.get("unrealized", 0)),
                })
        return balances

    def get_positions(self):
        """Get all open positions."""
        result = self._request("GET", "/api/v1/private/position/open_positions")
        if "error" in result:
            return result
        data = result.get("data", [])
        positions = []
        for pos in data:
            if float(pos.get("holdVol", 0)) > 0:
                positions.append({
                    "symbol": pos.get("symbol"),
                    "side": "long" if pos.get("positionType") == 1 else "short",
                    "size": float(pos.get("holdVol", 0)),
                    "entry_price": float(pos.get("openAvgPrice", 0)),
                    "mark_price": float(pos.get("markPrice", 0)),
                    "liquidation": float(pos.get("liquidatePrice", 0)),
                    "leverage": int(pos.get("leverage", 0)),
                    "margin": float(pos.get("im", 0)),
                    "unrealized_pnl": float(pos.get("unrealized", 0)),
                    "pnl_pct": float(pos.get("unRealizedProfitRate", 0)) * 100,
                })
        return positions

    # ── Trading ──

    def set_leverage(self, symbol, leverage):
        """Set leverage for a symbol."""
        # positionType 1=long, 2=short — set both
        for pos_type in [1, 2]:
            self._request("POST", "/api/v1/private/position/change_leverage", body={
                "symbol": symbol,
                "leverage": leverage,
                "positionType": pos_type,
            })
        return {"symbol": symbol, "leverage": leverage}

    def open_long(self, symbol, vol, leverage=8, stop_loss=None, take_profit=None):
        """Open a long position. vol = number of contracts."""
        self.set_leverage(symbol, leverage)
        body = {
            "symbol": symbol,
            "side": 1,  # 1=open long
            "type": 5,  # 5=market
            "vol": vol,
            "openType": 1,  # 1=isolated
            "leverage": leverage,
        }
        if stop_loss:
            body["stopLossPrice"] = stop_loss
        if take_profit:
            body["takeProfitPrice"] = take_profit

        result = self._request("POST", "/api/v1/private/order/submit", body=body)
        if "error" in result:
            return result
        return {"order_id": result.get("data"), "side": "long", "symbol": symbol, "vol": vol}

    def open_short(self, symbol, vol, leverage=8, stop_loss=None, take_profit=None):
        """Open a short position. vol = number of contracts."""
        self.set_leverage(symbol, leverage)
        body = {
            "symbol": symbol,
            "side": 3,  # 3=open short
            "type": 5,  # 5=market
            "vol": vol,
            "openType": 1,  # 1=isolated
            "leverage": leverage,
        }
        if stop_loss:
            body["stopLossPrice"] = stop_loss
        if take_profit:
            body["takeProfitPrice"] = take_profit

        result = self._request("POST", "/api/v1/private/order/submit", body=body)
        if "error" in result:
            return result
        return {"order_id": result.get("data"), "side": "short", "symbol": symbol, "vol": vol}

    def close_long(self, symbol, vol=None):
        """Close long position. If vol=None, closes entire position."""
        if vol is None:
            positions = self.get_positions()
            for p in positions:
                if p["symbol"] == symbol and p["side"] == "long":
                    vol = int(p["size"])
                    break
            if not vol:
                return {"error": "No long position found"}

        body = {
            "symbol": symbol,
            "side": 2,  # 2=close long
            "type": 5,
            "vol": vol,
            "openType": 1,
        }
        result = self._request("POST", "/api/v1/private/order/submit", body=body)
        if "error" in result:
            return result
        return {"order_id": result.get("data"), "action": "close_long", "symbol": symbol, "vol": vol}

    def close_short(self, symbol, vol=None):
        """Close short position. If vol=None, closes entire position."""
        if vol is None:
            positions = self.get_positions()
            for p in positions:
                if p["symbol"] == symbol and p["side"] == "short":
                    vol = int(p["size"])
                    break
            if not vol:
                return {"error": "No short position found"}

        body = {
            "symbol": symbol,
            "side": 4,  # 4=close short
            "type": 5,
            "vol": vol,
            "openType": 1,
        }
        result = self._request("POST", "/api/v1/private/order/submit", body=body)
        if "error" in result:
            return result
        return {"order_id": result.get("data"), "action": "close_short", "symbol": symbol, "vol": vol}

    def cancel_order(self, symbol, order_id):
        """Cancel an open order."""
        result = self._request("POST", "/api/v1/private/order/cancel", body={
            "symbol": symbol, "orderId": order_id
        })
        return result

    def get_open_orders(self, symbol=None):
        """Get open orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        result = self._request("GET", "/api/v1/private/order/list/open_orders", params)
        return result.get("data", result)

    def get_history(self, symbol=None, limit=10):
        """Get order history."""
        params = {"page_num": 1, "page_size": limit}
        if symbol:
            params["symbol"] = symbol
        result = self._request("GET", "/api/v1/private/order/list/history_orders", params)
        return result.get("data", result)


# ── CLI ──

def main():
    client = MexcFutures()

    if len(sys.argv) < 2:
        print("""MEXC Futures CLI
Commands:
  price [symbol]                    Get current price
  balance                           Account balance
  positions                         Open positions
  long [symbol] [vol] [lev]         Open long (market)
  short [symbol] [vol] [lev]        Open short (market)
  close [symbol]                    Close position
  cancel [symbol] [order_id]        Cancel order
  orders [symbol]                   Open orders
  history [limit]                   Order history

Options: --sl [price] --tp [price]

Examples:
  python3 mexc.py price ETH_USDT
  python3 mexc.py short ETH_USDT 100 8 --sl 2250 --tp 1800
  python3 mexc.py close ETH_USDT
""")
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    # Parse --sl and --tp from anywhere in args
    sl = tp = None
    clean_args = []
    i = 0
    while i < len(args):
        if args[i] == "--sl" and i + 1 < len(args):
            sl = float(args[i + 1]); i += 2
        elif args[i] == "--tp" and i + 1 < len(args):
            tp = float(args[i + 1]); i += 2
        else:
            clean_args.append(args[i]); i += 1
    args = clean_args

    if cmd == "price":
        symbol = args[0] if args else "ETH_USDT"
        result = client.get_price(symbol)
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"{result['symbol']}: ${result['price']:.2f}")
            print(f"  24h: {result['change24h']*100:+.2f}% | H: ${result['high24h']:.2f} L: ${result['low24h']:.2f}")
            print(f"  Vol: {result['volume24h']:,.0f} | Funding: {result['funding_rate']*100:.4f}%")

    elif cmd == "balance":
        result = client.get_balance()
        if isinstance(result, dict) and "error" in result:
            print(f"Error: {result['error']}")
        else:
            for b in result:
                print(f"{b['currency']}: ${b['equity']:.2f} (avail: ${b['available']:.2f}, pnl: ${b['unrealized_pnl']:.2f})")

    elif cmd == "positions":
        result = client.get_positions()
        if isinstance(result, dict) and "error" in result:
            print(f"Error: {result['error']}")
        elif not result:
            print("No open positions")
        else:
            for p in result:
                print(f"{p['symbol']} {p['side'].upper()} {p['size']} @ ${p['entry_price']:.2f}")
                print(f"  Mark: ${p['mark_price']:.2f} | Liq: ${p['liquidation']:.2f} | Lev: {p['leverage']}x")
                print(f"  PnL: ${p['unrealized_pnl']:.2f} ({p['pnl_pct']:+.2f}%) | Margin: ${p['margin']:.2f}")

    elif cmd == "long":
        if len(args) < 2:
            print("Usage: long [symbol] [vol] [leverage]")
            sys.exit(1)
        symbol, vol = args[0], int(args[1])
        lev = int(args[2]) if len(args) > 2 else 8
        result = client.open_long(symbol, vol, lev, stop_loss=sl, take_profit=tp)
        print(json.dumps(result, indent=2))

    elif cmd == "short":
        if len(args) < 2:
            print("Usage: short [symbol] [vol] [leverage]")
            sys.exit(1)
        symbol, vol = args[0], int(args[1])
        lev = int(args[2]) if len(args) > 2 else 8
        result = client.open_short(symbol, vol, lev, stop_loss=sl, take_profit=tp)
        print(json.dumps(result, indent=2))

    elif cmd == "close":
        if not args:
            print("Usage: close [symbol]")
            sys.exit(1)
        symbol = args[0]
        # Try closing both sides
        positions = client.get_positions()
        if isinstance(positions, list):
            for p in positions:
                if p["symbol"] == symbol:
                    if p["side"] == "long":
                        result = client.close_long(symbol)
                    else:
                        result = client.close_short(symbol)
                    print(json.dumps(result, indent=2))

    elif cmd == "cancel":
        if len(args) < 2:
            print("Usage: cancel [symbol] [order_id]")
            sys.exit(1)
        result = client.cancel_order(args[0], args[1])
        print(json.dumps(result, indent=2))

    elif cmd == "orders":
        symbol = args[0] if args else None
        result = client.get_open_orders(symbol)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "history":
        limit = int(args[0]) if args else 10
        result = client.get_history(limit=limit)
        print(json.dumps(result, indent=2, default=str))

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
