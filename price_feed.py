"""
Live order-book tracker over Polymarket's public CLOB market websocket.

Rather than polling REST every millisecond (which would get rate-limited
fast), we open one websocket per market cycle and let the server PUSH every
book/price update as it happens — updates typically land within a few ms of
the underlying trade. The bot's watch-loop then just reads the latest cached
value out of memory, which is effectively as fast as "every millisecond".

Tracks both the best bid/ask (for the entry/stop-loss triggers) AND full
depth per price level (so you can ask "how many shares are resting at
0.99?"), kept in sync from the same websocket events.
"""
import json
import threading
import time

import websocket  # pip package: websocket-client

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class _OrderBook:
    """price(rounded to 4dp) -> size, for one side of one token."""

    __slots__ = ("bids", "asks")

    def __init__(self):
        self.bids = {}
        self.asks = {}

    def apply_snapshot(self, bids, asks):
        self.bids = {round(float(l["price"]), 4): float(l["size"]) for l in (bids or [])}
        self.asks = {round(float(l["price"]), 4): float(l["size"]) for l in (asks or [])}

    def apply_change(self, side: str, price, size):
        book = self.bids if side == "BUY" else self.asks
        p = round(float(price), 4)
        s = float(size)
        if s <= 0:
            book.pop(p, None)
        else:
            book[p] = s

    def size_at(self, side: str, price) -> float:
        book = self.bids if side == "bid" else self.asks
        return book.get(round(float(price), 4), 0.0)


class PriceFeed:
    def __init__(self, token_ids):
        self.token_ids = list(token_ids)
        self._best_ask = {t: None for t in self.token_ids}
        self._best_bid = {t: None for t in self.token_ids}
        self._books = {t: _OrderBook() for t in self.token_ids}
        self._last_update = {t: 0.0 for t in self.token_ids}
        self._lock = threading.Lock()
        self._ws = None
        self._stop = False
        self._thread = None

    # -- public API ----------------------------------------------------
    def best_ask(self, token_id: str):
        with self._lock:
            return self._best_ask.get(token_id)

    def best_bid(self, token_id: str):
        with self._lock:
            return self._best_bid.get(token_id)

    def size_at_ask(self, token_id: str, price) -> float:
        """Shares resting on the ask (sell) side at exactly this price."""
        with self._lock:
            return self._books[token_id].size_at("ask", price)

    def size_at_bid(self, token_id: str, price) -> float:
        """Shares resting on the bid (buy) side at exactly this price."""
        with self._lock:
            return self._books[token_id].size_at("bid", price)

    def ask_depth(self, token_id: str) -> dict:
        """Copy of the full {price: size} ask book for this token."""
        with self._lock:
            return dict(self._books[token_id].asks)

    def bid_depth(self, token_id: str) -> dict:
        """Copy of the full {price: size} bid book for this token."""
        with self._lock:
            return dict(self._books[token_id].bids)

    def age(self, token_id: str) -> float:
        """Seconds since the last update for this token (staleness check)."""
        with self._lock:
            ts = self._last_update.get(token_id, 0.0)
        return time.time() - ts if ts else float("inf")

    def start(self):
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    # -- internals -------------------------------------------------------
    def _run_forever(self):
        backoff = 0.5
        while not self._stop:
            try:
                self._connect_and_listen()
                backoff = 0.5  # reset after a clean run
            except Exception as e:
                print(f"[price_feed] error: {e!r} — reconnecting in {backoff:.1f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 5.0)

    def _connect_and_listen(self):
        ws = websocket.create_connection(WS_URL, timeout=10)
        self._ws = ws
        ws.settimeout(5)
        ws.send(json.dumps({
            "assets_ids": self.token_ids,
            "type": "market",
            "custom_feature_enabled": True,
        }))

        last_rx = time.time()
        while not self._stop:
            try:
                raw = ws.recv()
                last_rx = time.time()
            except Exception:
                # no message within the timeout window — send a ping to
                # confirm the socket is still alive; raise if it isn't.
                if time.time() - last_rx > 15:
                    raise ConnectionError("no data or pong for 15s")
                try:
                    ws.ping()
                except Exception:
                    raise
                continue

            if raw:
                self._handle_raw(raw)

    def _handle_raw(self, raw: str):
        try:
            payload = json.loads(raw)
        except Exception:
            return
        messages = payload if isinstance(payload, list) else [payload]
        now = time.time()

        for msg in messages:
            event = msg.get("event_type")

            if event == "book":
                token = msg.get("asset_id")
                if token in self._books:
                    asks = msg.get("asks") or []
                    prices = [float(a["price"]) for a in asks if float(a.get("size", 0)) > 0]
                    bids = msg.get("bids") or []
                    bid_prices = [float(b["price"]) for b in bids if float(b.get("size", 0)) > 0]
                    with self._lock:
                        self._books[token].apply_snapshot(bids, asks)
                        if prices:
                            self._best_ask[token] = min(prices)
                        if bid_prices:
                            self._best_bid[token] = max(bid_prices)
                        self._last_update[token] = now

            elif event == "price_change":
                for change in msg.get("price_changes", []):
                    token = change.get("asset_id")
                    if token not in self._books:
                        continue
                    with self._lock:
                        self._books[token].apply_change(
                            change.get("side", "SELL"), change["price"], change["size"]
                        )
                        if "best_ask" in change and change["best_ask"] not in (None, ""):
                            self._best_ask[token] = float(change["best_ask"])
                        if "best_bid" in change and change["best_bid"] not in (None, ""):
                            self._best_bid[token] = float(change["best_bid"])
                        self._last_update[token] = now

            elif event == "best_bid_ask":
                token = msg.get("asset_id")
                if token in self._best_ask:
                    with self._lock:
                        self._best_ask[token] = float(msg["best_ask"])
                        self._best_bid[token] = float(msg["best_bid"])
                        self._last_update[token] = now

            elif event == "last_trade_price":
                # Not used for triggers directly, but useful context if you
                # want to log/extend the strategy later.
                pass
