# Sequence feature interpretation

The optional sequence feature stage starts from significant events in each
comparison and event class. A high-PSI event must have finite PSI >= the
user-selected high threshold in every control and treatment sample; a low-PSI
event must have finite PSI <= the user-selected low threshold in every sample
(defaults are 0.8 and 0.2). An
event that changes from low in controls to high in
treatment is excluded from both strata. The counts in the summary add strata
across comparisons and are not a count of unique event IDs.

For each nonempty stratum, ASTK produces splice-site strength, flanking GC
content, and log-scaled element length tables and figures. If both strata
have feature tables for a comparison and event class, `astk vcmp` generates
high-versus-low box plots using a two-sided Mann-Whitney test with
Benjamini-Hochberg correction. The plot and command output are saved under
`output/sequence_features/comparisons/` and included in the report ZIP.

The raw GC table contains a value for every sliding window position. To keep
the comparison interpretable, the comparison first averages finite positions
per event, splice site, and exon/intron region. The per-event regional tables
are saved alongside the plots. The original `gcc.csv` and `gcc.png` are
unchanged and remain available in the ZIP. Comparison failures are recorded
in `summary.json`; the main task may still complete, so inspect the module
status before interpreting a missing image.

This grouping differs from comparing mean PSI by condition, comparing
high-to-low transitions, or pooling all detected events. Choose the intended
biological contrast before drawing conclusions from these plots.
