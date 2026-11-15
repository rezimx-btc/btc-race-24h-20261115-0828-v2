"""RSI-gated dip-ladder bot for btc-race-24h-20261115-0828.

A different idea from a plain dip-buy: the bot only buys a dip that is
(a) deep against a LONG trailing high, (b) part of a sustained decline
rather than a one-bar spike, and (c) no longer in freefall. Three
relative gauges decide that, all in integer basis points, no absolute
price, bar index or timestamp anywhere:

  * DIP -- the latest close vs the highest close of the trailing 240
    bars. A buy needs a drop of at least 300 bps.
  * RSI(14) -- simple-average RSI over the last 14 one-minute closes.
    A buy needs RSI >= 2200 bps (22.00): the market must have stopped
    plunging. Bars with RSI in the teens are falling knives and are
    skipped even when the dip is deep.
  * RET120 -- the 120-bar return. A buy needs it at or below -180 bps:
    the decline must be sustained, not a single sharp bar off a flat
    base.

When those three agree, the 60-bar return splits the trade into two
regimes, with a deliberate dead zone between them:

  * SWING -- dip <= -370 bps AND 60-bar return <= -280 bps: a
    capitulation leg. The -280 bps bar is what keeps the bot out of
    the leg down to the real bottom: shallower 60-bar falls in the
    same dip are left alone (see dead zone). Take-profit +490 bps,
    stop-loss -200 bps, a trailing stop once +300 bps is reached
    (sell if the close falls 100 bps off the peak since entry),
    240-bar time stop.
  * SCALP -- 60-bar return > -160 bps: a shallow, grinding dip.
    Take-profit +70 bps, or +85 bps when the entry RSI was at least
    2500 bps: a dip that had already stabilised more (higher RSI)
    tends to bounce further, so it is worth holding for the extra
    15 bps; a dip bought right at the RSI floor is taken quick.
    Stop-loss -120 bps, 120-bar time stop. The stop is wider than
    the take-profit on purpose: a scalp that dips a little further
    usually recovers to the take-profit, while a tight stop exits
    exactly at the local bottom and then watches the bounce from cash.
  * DEAD ZONE -- anything in between (deep dip but only a middling
    60-bar fall, e.g. a dip that is still deepening): no trade. Buying
    there means catching the leg down to the real bottom and then
    having no cash left for it.

All take-profit / stop-loss levels are measured against the
cost-based entry price the replay reports (cost includes the buy's
fee and price impact, so the entry price sits above the fill price):
the thresholds are set net of that markup, which is why the swing
take-profit is 490 bps rather than a round 500 -- on the dev window
the +500 bps line sits a few bps above the recovery's top close and
never triggers, while 490 bps catches it.

Full size (100% of cash) on every buy, one open position at most, no
new entries in the final 60 bars, a 10-bar cooldown after any exit.
Orders fill at the next bar's open, so the bot decides on closes only.
Fully deterministic: integer math throughout, no clock, no network, no
files, no randomness -- the same bars always give the same orders.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- entry gates (bps; 100 bps = 1%) ---------------------------------------
WINDOW_BARS = 240         # trailing window for the reference high
DIP_BPS = 300             # buy when close <= high * (1 - 3.0%)
RSI_MIN_BPS = 2200        # buy only when RSI(14) >= 22.00 (not freefall)
RET120_BPS = 180          # buy only when the 120-bar return <= -1.8%
SWING_DIP_BPS = 370       # swing leg: dip <= -3.7% ...
SWING_RET60_BPS = 280     # ... and 60-bar return <= -2.8%
SCALP_RET60_BPS = 160     # scalp leg: 60-bar return > -1.6%
LAST_ENTRY_BAR = 1380     # no new entries in the final 60 bars
COOLDOWN_BARS = 10        # no re-entry within 10 bars of an exit

# --- scalp exits ------------------------------------------------------------
SCALP_TP_BPS = 70         # take-profit +0.70% (weak-RSI scalp)
SCALP_TP_STRONG_BPS = 85  # take-profit +0.85% (entry RSI >= 2500 bps)
SCALP_TP_STRONG_RSI_BPS = 2500
SCALP_SL_BPS = 120        # stop-loss -1.20%
SCALP_HOLD_BARS = 120     # time stop: sell after 120 bars held

# --- swing exits ------------------------------------------------------------
SWING_TP_BPS = 490        # take-profit +4.90%
SWING_SL_BPS = 200        # stop-loss -2.00%
SWING_TRAIL_ARM_BPS = 300  # arm the trailing stop once +3.0% over entry
SWING_TRAIL_DROP_BPS = 100  # ... then sell if close falls 1.0% off the peak
SWING_HOLD_BARS = 240     # time stop: sell after 240 bars held

MAX_SLIPPAGE_BPS = 1000   # 10% guard vs the latest close


def _bps(numerator, denominator):
    """numerator / denominator in basis points (floor division)."""
    return numerator * 10_000 // denominator


def _rsi_bps(closes):
    """Simple-average RSI(14) of the last 14 closes, in bps (0..10000).

    The 14 one-bar differences ending at the latest close; gains and
    losses are averaged separately, then RSI = 100 - 100 / (1 + RS).
    """
    gains = 0
    losses = 0
    for k in range(len(closes) - 14, len(closes)):
        diff = closes[k] - closes[k - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains // 14
    avg_loss = losses // 14
    if avg_loss == 0:
        return 10_000
    rs_bps = avg_gain * 10_000 // avg_loss
    return 10_000 - 100_000_000 // (10_000 + rs_bps)


def _entry_price(state):
    """Average entry price (price-scale ints) of the open position."""
    holding = state.positions.get(SYMBOL)
    if holding is None or holding.qty <= 0:
        return None
    sym = state.symbols[SYMBOL]
    quote_scale = state.hello["capital"]["quote_scale"]
    # cost (quote units, fees included) -> price int:
    # qty * price * 10**quote_scale // 10**(qty_scale + price_scale) = value
    return (
        holding.cost
        * 10 ** (sym["qty_scale"] + sym["price_scale"])
        // (holding.qty * 10**quote_scale)
    )


def on_batch(state, batch):
    # Only decide on a batch that actually carries a fresh bar for our
    # symbol; a gap minute leaves the last close stale.
    if not any(bar.get("symbol") == SYMBOL for bar in batch.get("bars", [])):
        return []
    if state.warming_up:
        return []

    close = state.close(SYMBOL)
    if close is None:
        return []

    closes.append(close)
    holding = state.positions.get(SYMBOL)

    if holding is not None and holding.qty > 0:
        entry_px = _entry_price(state)
        if entry_px is None or entry_px <= 0:
            return []
        if peak_since_entry[0] is None:
            peak_since_entry[0] = close
        else:
            peak_since_entry[0] = max(peak_since_entry[0], close)
        gain_bps = _bps(close - entry_px, entry_px)
        held_bars = state.seq - entry_bar[0]
        if mode[0] == "S":
            trail_drop_bps = _bps(peak_since_entry[0] - close, peak_since_entry[0])
            done = (
                gain_bps >= SWING_TP_BPS
                or (gain_bps >= SWING_TRAIL_ARM_BPS and trail_drop_bps >= SWING_TRAIL_DROP_BPS)
                or gain_bps <= -SWING_SL_BPS
                or held_bars >= SWING_HOLD_BARS
            )
        else:
            tp_bps = (
                SCALP_TP_STRONG_BPS
                if entry_rsi_bps[0] >= SCALP_TP_STRONG_RSI_BPS
                else SCALP_TP_BPS
            )
            done = (
                gain_bps >= tp_bps
                or gain_bps <= -SCALP_SL_BPS
                or held_bars >= SCALP_HOLD_BARS
            )
        if done:
            peak_since_entry[0] = None
            entry_bar[0] = -1
            last_exit_bar[0] = state.seq
            mode[0] = None
            return [
                {
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": holding.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
            ]
        return []

    # Flat: the three entry gates, then the regime split.
    if len(closes) < WINDOW_BARS or state.seq > LAST_ENTRY_BAR:
        return []
    if state.seq - last_exit_bar[0] < COOLDOWN_BARS:
        return []
    high = max(closes[-WINDOW_BARS:])
    dip_bps = _bps(close - high, high)
    if dip_bps > -DIP_BPS:
        return []
    rsi_bps = _rsi_bps(closes)
    if rsi_bps < RSI_MIN_BPS:
        return []
    ret120_bps = _bps(close - closes[-121], closes[-121])
    if ret120_bps > -RET120_BPS:
        return []
    ret60_bps = _bps(close - closes[-61], closes[-61])
    if dip_bps <= -SWING_DIP_BPS and ret60_bps <= -SWING_RET60_BPS:
        leg = "S"
    elif ret60_bps > -SCALP_RET60_BPS:
        leg = "s"
    else:
        return []  # dead zone: dip still deepening, wait for the bottom
    room = state.weight_room(SYMBOL)
    spend = min(state.cash, room)
    if spend < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    mode[0] = leg
    entry_bar[0] = state.seq
    entry_rsi_bps[0] = rsi_bps
    peak_since_entry[0] = None
    return [
        {
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": spend,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }
    ]


closes = []
peak_since_entry = [None]
entry_bar = [-1]
entry_rsi_bps = [0]
last_exit_bar = [-10**9]
mode = [None]

makefun_bars.run(on_batch)
