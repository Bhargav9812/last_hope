# Polymarket 5-Min Bot 4 -- late-window 0.99 limit buy

In the last `ARM_SECONDS_BEFORE_CLOSE` seconds (default 30) of each 5-minute
BTC Up/Down market, the bot watches both legs. When a leg's best ask reaches
`ENTRY_TRIGGER_PRICE` (0.99) AND fewer than `ENTRY_MAX_DEPTH_SHARES` (2000)
shares are resting at that price, it places ONE limit buy of
`ORDER_SIZE_SHARES` (10) at `ORDER_LIMIT_PRICE` (0.99). One entry per market.

- If the buy can't fill fully, the unfilled part stays resting on the book
  (no auto-cancel).
- There is no stop-loss / exit: the position is held to resolution.
- If the 0.99 level holds 2000+ shares it skips, but keeps watching and
  enters later in the window if the wall shrinks below 2000.
- Trading hours in IST (`START_TIME_IST` / `END_TIME_IST`) start/stop it
  automatically.

Prices and book depth come from Polymarket's public websocket (push-driven).

## Setup
Same account setup as the other bots: USDC deposited, one manual trade made
for approvals, private key, wallet address, and a Relayer API key
(polymarket.com -> Settings -> API Keys -> Relayer API Keys).

## Deploy on Railway
1. Put this folder in its own repo / Railway service.
2. Add the variables from `.env.example`. Keep `DRY_RUN=true` first.
3. Check logs: `USDC balance visible to bot: $...`, then `Active market: ...`
   every 5 minutes and `TRIGGER hit` lines (no real order while DRY_RUN=true).
4. When satisfied, set `DRY_RUN=false`.

## Risk
Not financial advice. Buying at 0.99 risks 0.99 per share to gain 0.01 per
share; a single reversal wipes out many winning trades, and with no
stop-loss the whole stake is exposed. Two bots on one account share one USDC
balance.
