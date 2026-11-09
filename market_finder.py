"""
Discovers the currently-active 5-minute Up/Down market using the official
polymarket-client SDK's public data client (no auth required).
"""
import time

from polymarket import AsyncPublicClient

import config


def current_window_start(now: float | None = None) -> int:
    now = now if now is not None else time.time()
    return int(now - (now % config.WINDOW_SECONDS))


def slug_for_window(window_start: int) -> str:
    minutes = config.WINDOW_SECONDS // 60
    return f"{config.ASSET}-updown-{minutes}m-{window_start}"


async def get_active_market(client: AsyncPublicClient, retries: int = 30, retry_delay: float = 0.5) -> dict:
    """Blocks (briefly) until the current window's market is indexed, then
    returns the parsed market info including window timing."""
    window_start = current_window_start()
    slug = slug_for_window(window_start)

    last_err = None
    for _ in range(retries):
        try:
            market = await client.get_market(slug=slug)
            up = market.outcomes.yes if market.outcomes.yes.label.strip().lower() in ("up", "yes") else market.outcomes.no
            down = market.outcomes.no if up is market.outcomes.yes else market.outcomes.yes

            return {
                "slug": market.slug,
                "up_token": str(up.token_id),
                "down_token": str(down.token_id),
                "tick_size": str(market.trading.minimum_tick_size or "0.01"),
                "window_start": window_start,
                "window_end": window_start + config.WINDOW_SECONDS,
            }
        except Exception as e:
            last_err = e
            time.sleep(retry_delay)

    raise RuntimeError(f"could not find market for slug={slug}: {last_err}")
