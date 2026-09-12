# Frozen prospective evaluation

No prospective result is published yet. The historical snapshot and development
challenge were used to correct the implementation. The public-tape supplement
is a reproduction check of one existing case, not an unseen evaluation.

## 1. Freeze before the observation period

Commit the finished source and pass the test suite first. Choose future UTC-hour
bounds that cover scheduled economic releases and allow enough preceding tape
for C1's 20 two-hour comparison windows. Select the series before inspecting
results. The dates below are an example future interval as of 2026-09-11;
replace them if that period has already started.

```bash
PYTHONPATH=src .venv/bin/python -m kxsurv.evaluate freeze \
  --manifest out/evaluations/october/manifest.json \
  --start 2026-10-01T00:00:00Z --end 2026-11-01T00:00:00Z \
  --series KXCPI KXCPIYOY KXPAYROLLS KXU3 KXFED
```

The manifest records its freeze timestamp, series, source commit, detector-code
hash, parameter hash, requirements hash, Python/package versions, endpoint, and
observation interval. Freezing a past interval or overwriting a manifest is
rejected. Retain or publish the manifest before the period starts; its local
timestamp alone is not independent attestation of pre-registration.

If needed, select the documented compatibility endpoint before **both** steps:

```bash
export KXSURV_API_BASE=https://api.elections.kalshi.com/trade-api/v2
```

## 2. Acquire after the interval finishes

Use the same source, parameters, dependencies, and endpoint. The acquisition
command rejects drift, an unfinished interval, and an existing output database.

```bash
PYTHONPATH=src .venv/bin/python -m kxsurv.evaluate acquire \
  --manifest out/evaluations/october/manifest.json \
  --db out/evaluations/october/snapshot.db \
  --output out/evaluations/october/run.json
```

This acquires a bounded public-data snapshot and runs all five controls.
It is retrospective computation over observations made after the method was
frozen; it does not measure real-time alert latency. Settlement labels and
source metadata are those available at acquisition, so record acquisition time
and do not treat them as information available to a trader during the interval.

The JSON initially reports untriaged candidates. Zero escalations before review
is not evidence that the candidates are benign. Save the database, manifest,
run JSON, source checkout, and environment together. A subsequent full ingest
must use another database. Preserve failed acquisition attempts and document
any retry rather than silently replacing them.

## 3. Review using the same written questions

For each candidate, document the observations, missing evidence, plausible
public-information or market-structure explanation, and the reason for closure,
monitoring, or escalation. Use `kxsurv.triage.disposition` to append decisions
and the existing export command to regenerate the run artifact after review.

```python
from kxsurv.db import connect
from kxsurv.triage import open_alerts, disposition

conn = connect("out/evaluations/october/snapshot.db")
for candidate in open_alerts(conn):
    print(candidate)
# After individually reviewing a candidate:
# disposition(conn, alert_id, "monitor", "Specific evidence and follow-up rationale")
conn.close()
```

```bash
PYTHONPATH=src .venv/bin/python -m kxsurv.cli \
  --db out/evaluations/october/snapshot.db \
  --export out/evaluations/october/run-reviewed.json
```

Do not change thresholds or mechanics in response to this evaluation and still
call it independent validation of the changed version. A necessary correction
makes this dataset development data for that revision; freeze a new later test.

## 4. Report what the sample supports

| Measure | Reporting rule |
|---|---|
| Acquisition coverage | State series, dates, markets, trades, candles, and reconciliation failures |
| C1 coverage | State scored markets and distinct publication dates; dependent contracts do not expand the independent sample |
| C3 selectivity | State scoreable observations, percentile-qualified observations, and persistent candidates |
| Analyst workload | State candidates, decisions, and untriaged remainder by control |
| Evidence quality | Distinguish a public explanation from an unresolved case lacking account data |
| Detection performance | Do not report precision, recall, or a false-positive rate without suitable labels |

Keep the prior baseline separate from the later result. A small or empty sample
is a coverage limitation to report, not a reason to choose another period after
seeing the result.
