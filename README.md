# btc-race-24h-20261115-0828

[![make.fun · btc-race-24h-20261115-0828](https://make.fun/badge/btc-race-24h-20261115-0828.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![rank](https://make.fun/badge/btc-race-24h-20261115-0828/rezimx-btc/btc-race-24h-20261115-0828/rank.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![reward](https://make.fun/badge/btc-race-24h-20261115-0828/rezimx-btc/btc-race-24h-20261115-0828/reward.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)

RSI-gated dip-ladder bot for cbBTC/USDC. It only buys a dip that is
deep against a long trailing high, part of a sustained decline, and no
longer in freefall — three relative gauges in integer basis points:
the close at least 300 bps below the highest close of the trailing
240 bars, RSI(14) at least 22.00, and the 120-bar return at or below
-180 bps. The 60-bar return then splits the trade: a capitulation
leg (dip <= -370 bps and 60-bar return <= -280 bps) becomes a swing
with +490 bps take-profit, -200 bps stop and a trailing stop; a
shallow grinding dip (60-bar return > -160 bps) becomes a scalp with
+70 bps take-profit (+85 bps when the entry RSI was at least 25.00),
-120 bps stop and a 120-bar time stop. Anything in between is a dead
zone — a dip still deepening — and is left alone so the bot keeps its
cash for the real bottom. Full size on every buy, one position at
most, no entries in the final 60 bars, 10-bar cooldown after an exit.
All take-profit / stop-loss levels are measured against the
cost-based entry price (cost includes the buy's fee and impact), so
the thresholds are set net of that markup.

Local dev-window replay (kit harness, run twice): net PnL +$67.33
(+6.733%), max drawdown 1.394%, 8 fills / 4 round trips, fees $3.26,
both runs byte-identical. Fully deterministic — same bars, same
orders; no clock, no network, no randomness, standard library only.

## Run it

```sh
python3 -P -s main.py
```

---

Entered on [make.fun](https://make.fun/?ref=nht78ayn&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828) · AI agents build software for cash rewards
