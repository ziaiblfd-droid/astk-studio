# Independently replay original ASTK R input parsing on saved length clusters.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args) >= 2)
suppressPackageStartupMessages(library(clusterProfiler))
suppressPackageStartupMessages(library(org.Mm.eg.db))
suppressPackageStartupMessages(library(readr))
source_dir <- args[1]
output_dir <- args[2]
keys <- if (length(args) > 2) args[-c(1, 2)] else c("facial_11.5_12_A3", "facial_11.5_12_AL")
bins <- c("1-51", "51-251", "251-1001")
matched <- 0L
for (key in keys) {
    gene_ls <- lapply(bins, function(bin) {
        path <- file.path(source_dir, "lenc", bin, paste0(key, ".sig.dpsi"))
        if (length(readLines(path, n=2, warn=FALSE)) < 2) return(character())
        d <- read_tsv(path, skip=1, col_names=FALSE,
                      col_types=cols("c", "d", "d"), progress=FALSE)
        # The original ASTK R script uses this extraction on versioned IDs.
        gsub("\\..*", "", d[[1]])
    })
    names(gene_ls) <- bins
    reference <- compareCluster(gene_ls, fun="enrichGO", pvalueCutoff=0.1,
        qvalueCutoff=0.1, OrgDb="org.Mm.eg.db", ont="BP",
        keyType="ENSEMBL", readable=TRUE)
    expected <- as.data.frame(reference)
    actual <- read.csv(file.path(output_dir, "enrichment_compare", key,
        "GO.cmp.BP.qval0.1_pval0.1.csv"), stringsAsFactors=FALSE, check.names=FALSE)
    stopifnot(nrow(expected) == nrow(actual))
    if (nrow(expected)) {
        ekey <- paste(expected$Cluster, expected$ID)
        akey <- paste(actual$Cluster, actual$ID)
        stopifnot(setequal(ekey, akey), !anyDuplicated(akey))
        actual <- actual[match(ekey, akey), , drop=FALSE]
        for (column in c("Description", "GeneRatio", "BgRatio", "Count")) {
            stopifnot(identical(as.character(actual[[column]]), as.character(expected[[column]])))
        }
        for (column in c("pvalue", "p.adjust", "qvalue")) {
            stopifnot(isTRUE(all.equal(actual[[column]], expected[[column]], tolerance=1e-10)))
        }
        stopifnot(all(vapply(seq_len(nrow(expected)), function(i)
            setequal(strsplit(actual$geneID[i], "/", fixed=TRUE)[[1]],
                     strsplit(expected$geneID[i], "/", fixed=TRUE)[[1]]), logical(1))))
    }
    matched <- matched + nrow(expected)
    cat(key, "matched", nrow(expected), "cluster GO rows\n")
}
cat("Independent ASTK comparison regression passed:", matched, "rows\n")
