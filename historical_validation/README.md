# ICT/SMC Historical Chart Validation

## Purpose

This directory defines a repeatable, evidence-based validation set for the XAUUSD ICT/SMC analyst. It is a dataset protocol, not proof of trading accuracy. No historical case is considered validated until its source data, point-in-time information boundary, and independent reference labels are present.

## Non-negotiable test integrity

1. **Point-in-time only:** each case must contain only candles and context that were available at its `as_of_utc`. Do not include candles that closed later in the prompt or image.
2. **Freeze before outcome:** save the model's first response before revealing subsequent price action. Never revise the original judgement using later candles.
3. **Separate facts from interpretation:** label observed swing points, breaks, sweeps and candle timestamps separately from the annotator's bias or preferred scenario.
4. **No invented levels:** every numeric zone, entry trigger, invalidation and target must be traceable to the supplied OHLC rows.
5. **Allow uncertainty and WAIT:** a case may be ambiguous or data-deficient. Do not force BUY/SELL labels.
6. **Independent labels:** ideally two experienced annotators label each case independently; resolve disagreements before scoring. Preserve disagreement where it cannot be resolved.
7. **Chronological split:** split by date/session, not random candles, to reduce leakage between highly correlated adjacent windows.
8. **Costs matter:** any execution simulation must declare spread, commission, slippage and price convention. Do not infer broker fills from candle OHLC alone.

## Dataset layout

One case directory per decision point:

```
historical_validation/
  README.md
  cases.template.json
  cases/
    .gitkeep
  predictions/
    .gitkeep
```

Keep raw chart screenshots and OHLC files with the case, or store a stable private reference if the data is licensed/restricted. Do not commit API keys, account identifiers, private customer data or broker credentials.

## Case record

Copy `cases.template.json` for each case. Required fields:

- `case_id`: stable unique ID.
- `as_of_utc`: exact decision cutoff.
- `instrument`: XAUUSD.
- `timeframes`: source files for H1/M15/M5; each file must end at or before cutoff.
- `market_context`: only contemporaneous calendar/currency/yield/news facts; use `UNKNOWN` when unavailable.
- `reference`: independently annotated context and decision label.
- `outcome_window`: later candles kept separate from model input, for post-decision outcome review only.

The template deliberately separates `model_input` from `outcome_window`. Never concatenate them into the same model request.

## Reference annotation rubric

Annotators should record what is visible, not what they wish the market had done:

- Higher-timeframe context: bullish, bearish, range, unclear.
- M15/M5 structure: relevant HH/HL or LH/LL, BOS/CHoCH/MSS with candle timestamps.
- Liquidity: pool/swing level and whether a sweep is actually confirmed.
- POI: OB/FVG/supply/demand/liquidity zone with OHLC-backed bounds, or none.
- Setup state at cutoff: WAIT, APPROACH, CONFIRMED, or DATA_INSUFFICIENT.
- If confirmed: direction, trigger timestamp, structural invalidation, and at least 1R target availability after declared costs.
- If no valid trade: objective reason, not hindsight or vague discomfort.

## Scoring — report dimensions separately

Do not compress everything into one accuracy percentage.

1. **Bias agreement:** higher-timeframe directional context agreement; exclude genuinely unclear cases from directional denominator and report count.
2. **Structure evidence:** whether cited breaks/sweeps and timestamps are present in supplied candles.
3. **Zone accuracy:** overlap between predicted and reference zones (report intersection-over-union where both zones exist); separately count unsupported/invented levels.
4. **Readiness classification:** confusion matrix for WAIT / APPROACH / CONFIRMED / DATA_INSUFFICIENT.
5. **Risk geometry:** whether invalidation is structurally defensible and first target offers at least 1R after declared costs.
6. **Outcome review:** report MFE/MAE and whether target/stop was reached first only when sufficiently granular OHLC and execution assumptions exist. If both levels occur in one candle, mark ambiguous unless lower-timeframe data resolves order.
7. **Calibration:** compare confidence buckets with observed outcomes only after enough cases; do not call subjective stars a probability.

Always publish sample size, date range, long/short/WAIT distribution, missing-data rate, ambiguous outcomes, and per-session breakdown. Include a baseline (for example, always-WAIT) so apparent performance is not overstated.

## Required evidence before claiming accuracy

A usable pilot needs a representative sample across trend, range, news volatility, quiet sessions, long and short opportunities, plus WAIT cases. A small curated set is useful for debugging but cannot establish profitability or generalization. Keep a locked out-of-sample period untouched until prompt/model changes are frozen.

## Current status

No independently annotated historical XAUUSD dataset is included yet. The repository's current three-timeframe workflow and contract tests verify data handling/output shape, not ICT chart-reading accuracy. Do not describe the analyst as historically validated until a labeled dataset has been run and results reviewed.
