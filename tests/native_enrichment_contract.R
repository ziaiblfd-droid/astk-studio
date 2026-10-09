# Base-R parser regressions, using the production read_genes definition.
args <- commandArgs(trailingOnly=TRUE)
expressions <- parse(file=args[1])
for (expression in expressions) {
    if (is.call(expression) && identical(expression[[1]], as.name("<-")) &&
        identical(expression[[2]], as.name("read_genes"))) eval(expression)
}
stopifnot(exists("read_genes", mode="function"))
directory <- tempfile("astk-parser-")
dir.create(directory)
rows <- c(
    "ENSMUSG00000000127.15;A3:chr17:1-2:1-3:+\t-0.1\t0.01",
    "ENSMUSG00000000600;A3:chr5:1-2:1-3:+\t0.2\t0.02",
    "ENSMUSG00000000127.15;A3:chr17:1-2:1-4:+\t0.3\t0.03"
)
expected <- c("ENSMUSG00000000127", "ENSMUSG00000000600")
for (header in c("event_id\tdpsi\tp_value", "dpsi\tp_value", "\tdpsi\tp_value")) {
    path <- file.path(directory, "events.dpsi")
    writeLines(c(header, rows), path)
    stopifnot(identical(read_genes(path), expected))
    writeLines(header, path)
    stopifnot(identical(read_genes(path), character()))
}
unlink(directory, recursive=TRUE)
cat("ASTK parser header and empty-input regressions passed\n")
