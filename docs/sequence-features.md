# Sequence feature interpretation

The optional sequence feature stage follows the reference ASTK `pf` workflow.
It uses all event PSI values separately for each condition and event class,
deduplicating a baseline reused in several comparisons. An event with finite
PSI in every replicate is high when its mean within that condition is at least
the user-selected high threshold, or low when its mean is at most the low
threshold (defaults: 0.8 and 0.2). No dPSI significance filter is applied.
The counts in the summary add strata across conditions and are not a count
of unique event IDs. A changing event may appear in opposite strata at
different conditions; the comparison plots compare high and low within one
condition, not across time points.

For each nonempty stratum, ASTK produces splice-site strength, flanking GC
content, and log-scaled element length tables and figures. If both strata
have feature tables for a condition and event class, `astk vcmp` generates
high-versus-low box plots using a two-sided Mann-Whitney test, as in the
reference comparison script. The plot and command output are saved under
`output/sequence_features/comparisons/` and included in the report ZIP.

Single-stratum GC profiles use 75 bp sliding windows over 150 bp exon/intron
flanks. A separate extraction with 150 bp windows is saved under
`gc_comparison/` and fed directly into `vcmp --facet`, retaining separate
splice sites and exon/intron windows. The old website averaged its 75 bp
windows by region and plotted all regions together; that changed both the
data represented and the visual layout. Comparison failures are recorded in
`summary.json`; the main task may still complete, so inspect the module
status before interpreting a missing image.

The original script's later `-alt` extraction is for the separate machine
learning workflow, not the sequence-feature comparison figures. Element
length is already log-scaled by `getlen --scale log`; the website does not
apply the script's additional `vcmp -log` (which would log-transform it twice).
Previously completed jobs retain their original figures; rerun the analysis
to obtain the revised condition-level plots.

## Execution and resources

The queue runs at most three jobs concurrently. A sequence-feature job runs
up to eight extraction or comparison commands in parallel (configurable via
`ASTK_SEQUENCE_WORKERS`, capped at eight). For each event class it extracts
sequence-derived values once from the union of the selected event IDs across
conditions, then writes the same per-condition high/low CSV values and figures
from that shared job-local catalog. The temporary catalog is removed after
the feature stage. This cache is per job: it does not share results between
different users' jobs or assume the genome reference is unchanged.

`summary.json` records the sequence-stage elapsed time and per-command
timings. During extraction, figure generation, and comparison the job's
stage/progress is updated. More RAM does not accelerate an idle server; tune
the parallel limit downward if concurrent jobs cause memory or disk pressure.
