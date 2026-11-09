from polymarket import AsyncSecureClient

import config


class OrderExecutor:
    """Places one LIMIT buy for the exact share count. If it can't fill in
    full right away, the remainder stays resting on the book (GTC) -- it is
    NOT auto-cancelled."""

    def __init__(self, client: AsyncSecureClient):
        self.client = client
        self._bought_tokens = set()  # guards against double-buying a token in one cycle

    async def buy(self, token_id: str, label: str, size: float, live_price: float | None = None):
        if token_id in self._bought_tokens:
            print(f"    skip: already bought {label} this cycle")
            return None

        price = config.ORDER_LIMIT_PRICE
        price_note = f" (live ask at trigger was {live_price})" if live_price is not None else ""
        print(f">>> TRIGGER hit — placing LIMIT buy: {size} shares of {label} @ {price}{price_note} "
              f"(token {token_id})")

        if config.DRY_RUN:
            print("    DRY_RUN=true — no order sent. Set DRY_RUN=false to go live.")
            self._bought_tokens.add(token_id)
            return None

        try:
            resp = await self.client.place_limit_order(
                token_id=token_id,
                side="BUY",
                price=price,
                size=size,
            )
            if resp.ok:
                print(f"    order accepted: id={resp.order_id} status={resp.status} "
                      f"making={resp.making_amount} taking={resp.taking_amount}")
                if resp.status != "matched":
                    print("    not fully filled immediately — left resting on the "
                          "book (no auto-cancel) so it can still fill later.")
            else:
                print(f"    order rejected: code={resp.code} message={resp.message}")
            self._bought_tokens.add(token_id)
            return resp
        except Exception as e:
            print(f"    ORDER FAILED for {label}: {e!r}")
            return None

    def reset(self):
        self._bought_tokens.clear()
