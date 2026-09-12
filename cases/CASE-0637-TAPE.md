# Public-tape supplement — KXPAYROLLS-26AUG-T-25000

Retrieved: 2026-09-11T17:12:58.483448+00:00

Published reference: run 8, alert 697, source commit `6b11825`.

This is a fresh retrieval from the public API. Agreement with the summary does not establish identity with every row of the original snapshot. The published artifact and its disposition remain unchanged.

## Timeline

- Scored interval: `[2026-09-04T10:29:00Z, 2026-09-04T12:29:00Z)` (UTC).
- Halt-to-release gap in the published record: 1.0 minute(s).

## Reconciliation

| Metric | Published | Re-fetched | Matches |
|---|---:|---:|---|
| Trade count | 7 | 7 | yes |
| Window volume | 212.18 | 212.18 | yes |
| C1 score | 0.3450400603 | 0.3450400603 | yes |
| Non-empty comparison windows | 16 | 16 | yes |
| Percentile | 100 | 100 | yes |

## Trades in the scored window

Contribution is contracts × direction × surprise / total window volume. Direction is +1 for buying the eventual outcome and −1 otherwise.

| Timestamp | Contracts | YES price | Aggressor bought | Surprise | Score contribution |
|---|---:|---:|---|---:|---:|
| 2026-09-04T11:44:40.284322Z | 5.00 | 0.7700 | no | 0.2300 | -0.00541993 |
| 2026-09-04T11:44:40.796193Z | 5.00 | 0.3400 | no | 0.6600 | -0.01555283 |
| 2026-09-04T11:44:40.802763Z | 90.00 | 0.3400 | yes | 0.6600 | 0.27995099 |
| 2026-09-04T11:55:47.153076Z | 1.18 | 0.8300 | yes | 0.1700 | 0.00094542 |
| 2026-09-04T12:07:07.234866Z | 55.00 | 0.8400 | yes | 0.1600 | 0.04147422 |
| 2026-09-04T12:09:41.40135Z | 50.00 | 0.8400 | yes | 0.1600 | 0.03770384 |
| 2026-09-04T12:25:55.411302Z | 6.00 | 0.7900 | yes | 0.2100 | 0.00593835 |

## Comparison windows

Empty windows are shown explicitly and excluded from the percentile population.

| Start UTC (inclusive) | End UTC (exclusive) | Trades | Contracts | C1 score |
|---|---|---:|---:|---:|
| 2026-09-04T08:29:00Z | 2026-09-04T10:29:00Z | 2 | 750.00 | 0.16000000 |
| 2026-09-04T06:29:00Z | 2026-09-04T08:29:00Z | 4 | 106.35 | -0.17924965 |
| 2026-09-04T04:29:00Z | 2026-09-04T06:29:00Z | 7 | 256.52 | 0.12428816 |
| 2026-09-04T02:29:00Z | 2026-09-04T04:29:00Z | 13 | 934.85 | 0.16803177 |
| 2026-09-04T00:29:00Z | 2026-09-04T02:29:00Z | 5 | 227.00 | 0.10052863 |
| 2026-09-03T22:29:00Z | 2026-09-04T00:29:00Z | 4 | 97.00 | -0.00752577 |
| 2026-09-03T20:29:00Z | 2026-09-03T22:29:00Z | 9 | 313.95 | 0.15092053 |
| 2026-09-03T18:29:00Z | 2026-09-03T20:29:00Z | 3 | 27.77 | 0.15221102 |
| 2026-09-03T16:29:00Z | 2026-09-03T18:29:00Z | 3 | 307.00 | 0.16993485 |
| 2026-09-03T14:29:00Z | 2026-09-03T16:29:00Z | 5 | 36.38 | -0.08142386 |
| 2026-09-03T12:29:00Z | 2026-09-03T14:29:00Z | 1 | 39.00 | 0.16000000 |
| 2026-09-03T10:29:00Z | 2026-09-03T12:29:00Z | 0 | 0.00 | excluded: empty |
| 2026-09-03T08:29:00Z | 2026-09-03T10:29:00Z | 0 | 0.00 | excluded: empty |
| 2026-09-03T06:29:00Z | 2026-09-03T08:29:00Z | 0 | 0.00 | excluded: empty |
| 2026-09-03T04:29:00Z | 2026-09-03T06:29:00Z | 1 | 1.00 | 0.15000000 |
| 2026-09-03T02:29:00Z | 2026-09-03T04:29:00Z | 4 | 77.58 | 0.15992524 |
| 2026-09-03T00:29:00Z | 2026-09-03T02:29:00Z | 2 | 17.34 | 0.16000000 |
| 2026-09-02T22:29:00Z | 2026-09-03T00:29:00Z | 0 | 0.00 | excluded: empty |
| 2026-09-02T20:29:00Z | 2026-09-02T22:29:00Z | 10 | 96.11 | 0.16582666 |
| 2026-09-02T18:29:00Z | 2026-09-02T20:29:00Z | 1 | 55.00 | 0.17000000 |

## Interpretation

A high relative rank is a screening result. These comparison windows are sparse, dependent observations and do not calibrate a false-positive rate. Public-information processing remains an alternative explanation; account identity and access to non-public information are unavailable.
