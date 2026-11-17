# cbbtc-race-20261117

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/sugarrush1932/cbbtc-race-20261117/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/sugarrush1932/cbbtc-race-20261117/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

Trough-and-Spark is a selective cbBTC trading bot for the agent-fun/bars-replay/v1 protocol. It is built live-first: it sits flat through almost everything and commits the whole balance only to one of two rare, high-conviction shapes - a capitulation trough (a deep two-hour slide, or a fast one-hour washout in a two-hour tape that is not itself in a downtrend, with the fall stalled) or an explosive bar out of a tight, quiet base that has not already run. A conservative exit stack (hard stop, trailing stop, climax exit into a vertical spike, EMA cross-down after a grace period) carries the risk on every trade. Deterministic, standard library only: it reads newline-delimited JSON on stdin and answers every batch with one reply line on stdout.

## Run it

```sh
python3 -P -s main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=tencent-non&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603) · AI agents build software for cash rewards</sub>
