# Sequence-feature performance check (2026-09-24)

The isolated benchmark ran on the Linux server with
`data/public-e2e-20260923/quant.zip` and
`data/public-e2e-20260923/samples.csv`. The ZIP SHA-256 is
`03806fba317f517fffc969b6f5fc98bf7b4f5944b08affa8a65a08f69645094a`.
It contains the same quantifications as the earlier completed job
`ASTK-260923-204503-36A1`; the sample tables use different row organization
but resolve to the same 10 samples.

The benchmark ran in `/home/yushiye/astk-web/perf-20260924` against an
isolated release, with `ASTK_SEQUENCE_WORKERS=8`,
`ASTK_FEATURE_PROCESSES=2`, and 0.8/0.2 PSI thresholds. No production job
or historical output was overwritten.

| Measure | Result |
| --- | ---: |
| Full job wall time, including report ZIP | 2402.06 s (40m 02s) |
| Sequence-feature stage | 1647.194 s (27m 27s) |
| Analysis units / high-low comparison figures / failures | 70 / 105 / 0 |
| Selected high/low events across conditions | 284,598 |
| Final job directory | 3,173,804,786 bytes (2.96 GiB) |
| Report ZIP | 224,754,974 bytes (214 MiB) |
| Peak sampled job-process RSS sum | 6,440,820,736 bytes (6.00 GiB) |
| Peak sampled job CPU | 15.47 cores (12.9% of 120 logical CPUs) |
| Peak sampled host CPU utilization | 28.29% |
| Lowest sampled host available RAM | 526,070,308,864 bytes (490 GiB) |

The old same-quantification job took about 16,639.63 s (4h 37m 20s) and
occupied 7,546,914,215 bytes (7.03 GiB) on disk. The new wall time is
about 6.9 times shorter. This is one workload, not a concurrency or
multiple-run benchmark. The 5-second resource sampler can miss short peaks;
the process RSS sum can count shared pages more than once. Host CPU includes
unrelated processes. Do not interpret `ASTK_SEQUENCE_WORKERS=8` as a
limit on total OS processes: ASTK may create its own child workers.

The 280 main feature CSV tables (four features across 70 strata) match the
old run after sorting rows and normalizing line endings. The 105 comparison
plots were generated and `unzip -t` passed. `spliceScore` on the AF event
union took 1389.973 s and remains the main single-command bottleneck.

Reproduce with `scripts/benchmark-job.py` on Linux. It writes
`benchmark.json` and `resource-samples.csv` alongside the isolated job.
