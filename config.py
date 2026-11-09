"""
All tunables live here and are read from environment variables so the bot
can be configured purely through Railway's Variables tab — no code edits
needed per deployment.
"""
import os


def _get_bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


# --- Wallet / account auth --------------------------------------------------
# Your account's signer private key (e.g. exported from
# reveal.magic.link/polymarket for an email/Magic-link account).
PRIVATE_KEY = os.environ["PK"]

# The account's wallet address — the address shown in your profile dropdown
# on polymarket.com, i.e. the one you deposit USDC to.
WALLET_ADDRESS = os.environ["WALLET"]

# A Relayer API key created at polymarket.com -> Settings -> API Keys ->
# Relayer API Keys. This authorizes gasless wallet operations for the
# account (this is what lets the SDK's Deposit-Wallet-aware signing work
# correctly, unlike the raw CLOB client).
RELAYER_API_KEY = os.environ["RELAYER_API_KEY"]
RELAYER_API_KEY_ADDRESS = os.environ["RELAYER_API_KEY_ADDRESS"]

# --- Trading hours (IST, 24hr format HH:MM) --------------------------------
# The bot only runs cycles between these times each day (IST = UTC+5:30,
# no DST). Outside this window it sleeps and checks again periodically --
# no need to start/stop the container by hand. Set START=00:00 and
# END=23:59 (the defaults) to run around the clock.
START_TIME_IST = os.environ.get("START_TIME_IST", "00:00")
END_TIME_IST = os.environ.get("END_TIME_IST", "23:59")

# --- Market selection ------------------------------------------------------
# Polymarket's 5-min crypto Up/Down markets use a deterministic slug:
#   {asset}-updown-5m-{window_start_unix_epoch}
ASSET = os.environ.get("ASSET", "btc")          # btc | eth | sol | xrp | doge | bnb ...
WINDOW_SECONDS = int(os.environ.get("WINDOW_SECONDS", "300"))  # 5 minutes

# --- Strategy parameters ----------------------------------------------------
# Start watching both legs this many seconds before the market closes.
ARM_SECONDS_BEFORE_CLOSE = float(os.environ.get("ARM_SECONDS_BEFORE_CLOSE", "30"))

# When either leg's best ask reaches this price, buy that leg.
ENTRY_TRIGGER_PRICE = float(os.environ.get("ENTRY_TRIGGER_PRICE", "0.99"))

# Only take the entry if the resting size at the trigger price is BELOW
# this many shares -- skips entries into an unusually large wall at 0.99.
ENTRY_MAX_DEPTH_SHARES = float(os.environ.get("ENTRY_MAX_DEPTH_SHARES", "2000"))

# Limit price used for the entry order.
ORDER_LIMIT_PRICE = float(os.environ.get("ORDER_LIMIT_PRICE", "0.99"))

# Share size for the entry order.
ORDER_SIZE_SHARES = float(os.environ.get("ORDER_SIZE_SHARES", "10"))

# How often the internal watch-loop re-checks cached prices. The actual
# price data itself arrives push-driven over the public websocket
# (sub-ms as trades happen); this just bounds how often we re-evaluate the
# trigger conditions.
POLL_INTERVAL_SEC = float(os.environ.get("POLL_INTERVAL_SEC", "0.002"))  # 2ms

# Safety switch. Defaults to true so nothing trades until you deliberately
# flip it off in Railway's variables once you've verified logs look right.
DRY_RUN = _get_bool("DRY_RUN", "true")

GAMMA_HOST = os.environ.get("GAMMA_HOST", "https://gamma-api.polymarket.com")
