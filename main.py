import asyncio
import time
import traceback
from datetime import datetime, timedelta, timezone

from polymarket import AsyncPublicClient, AsyncSecureClient, RelayerApiKey, AssetType

import config
import market_finder
from price_feed import PriceFeed
from executor import OrderExecutor

IST = timezone(timedelta(hours=5, minutes=30))


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.strip().split(":")
    return int(h), int(m)


def is_within_trading_window(now_ist: datetime, start_hm: tuple, end_hm: tuple) -> bool:
    start_min = start_hm[0] * 60 + start_hm[1]
    end_min = end_hm[0] * 60 + end_hm[1]
    now_min = now_ist.hour * 60 + now_ist.minute
    if start_min <= end_min:
        return start_min <= now_min < end_min
    # window wraps past midnight (e.g. 22:00 -> 02:00)
    return now_min >= start_min or now_min < end_min


def seconds_until_window_start(now_ist: datetime, start_hm: tuple) -> float:
    target = now_ist.replace(hour=start_hm[0], minute=start_hm[1], second=0, microsecond=0)
    if target <= now_ist:
        target += timedelta(days=1)
    return (target - now_ist).total_seconds()


async def build_secure_client() -> AsyncSecureClient:
    return await AsyncSecureClient.create(
        private_key=config.PRIVATE_KEY,
        wallet=config.WALLET_ADDRESS,
        api_key=RelayerApiKey(
            key=config.RELAYER_API_KEY,
            address=config.RELAYER_API_KEY_ADDRESS,
        ),
    )


async def log_usdc_balance(client: AsyncSecureClient):
    """Prints the USDC balance the bot's wallet config actually sees, so you
    can confirm it's pointed at the wallet that holds your real funds
    BEFORE it ever places a live order."""
    try:
        bal = await client.get_balance_allowance(asset_type="COLLATERAL")
        usdc = bal.balance / 1_000_000  # USDC has 6 decimals
        log(f"USDC balance visible to bot: ${usdc:,.2f} (wallet={client.wallet})")
        if usdc == 0:
            log("WARNING: balance shows $0. If you expect funds here, double-check "
                "WALLET and the Relayer API key/address — you're likely pointed at "
                "the wrong account (see README).")
    except Exception as e:
        log(f"Balance check failed: {e!r}")


async def run_cycle(public_client: AsyncPublicClient, secure_client: AsyncSecureClient):
    market = await market_finder.get_active_market(public_client)
    log(f"Active market: {market['slug']}")

    up_token = market["up_token"]
    down_token = market["down_token"]
    window_end = market["window_end"]

    arm_at = window_end - config.ARM_SECONDS_BEFORE_CLOSE
    now = time.time()

    if now >= window_end - 3:
        log("Too close to / past window close already, skipping to next window.")
        await _sleep_until(window_end + 1)
        return

    if arm_at > now:
        log(f"Sleeping {arm_at - now:.1f}s until arm time (T-{config.ARM_SECONDS_BEFORE_CLOSE:.0f}s)")
        await asyncio.sleep(arm_at - now)

    feed = PriceFeed([up_token, down_token])
    feed.start()
    executor = OrderExecutor(secure_client)

    position_leg = None     # "up" | "down" | None -- which leg (if any) we've entered
    depth_skip_logged = set()  # avoids re-logging an identical skip every poll tick

    log("Armed — watching both legs' best-ask price for entry.")
    try:
        while True:
            now = time.time()
            if now >= window_end:
                log("Window closed.")
                break

            if position_leg is not None:
                # Already entered this cycle -- one entry per market, nothing
                # else to do (no stop-loss). Wait out the rest of the window.
                await asyncio.sleep(config.POLL_INTERVAL_SEC)
                continue

            up_ask = feed.best_ask(up_token)
            down_ask = feed.best_ask(down_token)

            if up_ask is not None and up_ask >= config.ENTRY_TRIGGER_PRICE:
                depth = feed.size_at_ask(up_token, up_ask)
                if depth < config.ENTRY_MAX_DEPTH_SHARES:
                    log(f"UP hit {up_ask} — {depth} shares resting (< {config.ENTRY_MAX_DEPTH_SHARES} cap) — entering")
                    await executor.buy(up_token, "UP", config.ORDER_SIZE_SHARES, up_ask)
                    position_leg = "up"
                elif "up" not in depth_skip_logged:
                    log(f"UP hit {up_ask} but {depth} shares resting (>= {config.ENTRY_MAX_DEPTH_SHARES} cap) — skipping entry")
                    depth_skip_logged.add("up")
            elif down_ask is not None and down_ask >= config.ENTRY_TRIGGER_PRICE:
                depth = feed.size_at_ask(down_token, down_ask)
                if depth < config.ENTRY_MAX_DEPTH_SHARES:
                    log(f"DOWN hit {down_ask} — {depth} shares resting (< {config.ENTRY_MAX_DEPTH_SHARES} cap) — entering")
                    await executor.buy(down_token, "DOWN", config.ORDER_SIZE_SHARES, down_ask)
                    position_leg = "down"
                elif "down" not in depth_skip_logged:
                    log(f"DOWN hit {down_ask} but {depth} shares resting (>= {config.ENTRY_MAX_DEPTH_SHARES} cap) — skipping entry")
                    depth_skip_logged.add("down")

            await asyncio.sleep(config.POLL_INTERVAL_SEC)
    finally:
        feed.stop()


async def _sleep_until(ts: float):
    delay = max(0.0, ts - time.time())
    if delay:
        await asyncio.sleep(delay)


async def main():
    log(f"Starting Bot 4 | asset={config.ASSET} | DRY_RUN={config.DRY_RUN} "
        f"| trading_hours={config.START_TIME_IST}-{config.END_TIME_IST} IST "
        f"| arm={config.ARM_SECONDS_BEFORE_CLOSE}s before close "
        f"| entry_trigger={config.ENTRY_TRIGGER_PRICE} "
        f"| size={config.ORDER_SIZE_SHARES} @ up to {config.ORDER_LIMIT_PRICE}")

    start_hm = _parse_hhmm(config.START_TIME_IST)
    end_hm = _parse_hhmm(config.END_TIME_IST)

    async with AsyncPublicClient() as public_client:
        secure_client = await build_secure_client()
        log("Secure client ready.")
        await log_usdc_balance(secure_client)

        while True:
            now_ist = datetime.now(IST)
            if not is_within_trading_window(now_ist, start_hm, end_hm):
                wait = seconds_until_window_start(now_ist, start_hm)
                log(f"Outside trading hours ({config.START_TIME_IST}-{config.END_TIME_IST} IST, "
                    f"now {now_ist.strftime('%H:%M')} IST) — sleeping "
                    f"{wait / 60:.1f} min until the window opens.")
                # sleep in chunks so a redeploy with new hours takes effect
                # without waiting out the whole remaining duration
                await asyncio.sleep(min(wait, 300))
                continue

            try:
                await run_cycle(public_client, secure_client)
            except Exception:
                log("ERROR in cycle:")
                traceback.print_exc()
                await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
