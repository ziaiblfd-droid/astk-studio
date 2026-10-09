# ASTK GO-BP adapter. Statistical calls and defaults match ASTK R/utils.R.
# Local fixes concern event-ID parsing, warning handling and valid empty PNGs.
suppressPackageStartupMessages(library(clusterProfiler))
suppressPackageStartupMessages(library(ggplot2))
suppressPackageStartupMessages(library(jsonlite))
m <- fromJSON(commandArgs(trailingOnly=TRUE)[1], simplifyVector=FALSE)
source(m$astk_utils)
org_name <- if (m$species == "mm10") "org.Mm.eg.db" else "org.Hs.eg.db"
suppressPackageStartupMessages(library(org_name, character.only=TRUE))
org <- get(org_name)
out <- m$output
set.seed(1)

read_genes <- function(path) {
    # ASTK formerly removed everything after a dot; versionless IDs retained
    # ";SE:..." and failed mapping. Split the event ID before removing version.
    # ASTK's lenCluster writes a two-field header above three-field rows
    # (index_label=FALSE). Reading with header=TRUE silently consumes event IDs
    # as row names. Match ASTK's explicit skip=1 parsing for both header forms.
    if (length(readLines(path, warn=FALSE, n=2)) < 2) return(character())
    d <- read.delim(path, header=FALSE, skip=1, check.names=FALSE,
                    stringsAsFactors=FALSE, col.names=c("event_id", "dpsi", "pvalue"))
    if (!nrow(d)) return(character())
    unique(sub("\\..*$", "", sub(";.*$", "", d[[1]])))
}
write_json_atomic <- function(value, path) {
    temp <- paste0(path, ".tmp")
    write_json(value, temp, auto_unbox=TRUE, pretty=TRUE, null="null", na="null")
    if (!file.rename(temp, path)) stop("Could not publish native job metadata")
}
empty_plot <- function(path, text) {
    p <- ggplot() + annotate("text", x=0, y=0, label=text, size=4) +
        xlim(-1, 1) + ylim(-1, 1) + theme_void() + ggtitle("GO BP")
    save_fig(p, path, format="png", width=6, height=4)
}
style_plot <- function(p, compare=FALSE) {
    p + scale_color_gradientn(colours=c("#b3eebe", "#46bac2", "#371ea3"),
                              guide=guide_colorbar(reverse=TRUE, order=1)) +
        guides(size=guide_legend(override.aes=list(shape=1))) +
        scale_y_discrete(labels=function(x) stringr::str_wrap(x, width=if (compare) 30 else 32)) +
        theme(panel.grid.major.y=element_line(linetype="dotted", color="#808080"),
              panel.grid.major.x=element_blank(),
              axis.text.y=element_text(size=if (compare) 8 else 9, lineheight=0.9),
              axis.text.x=element_text(angle=if (compare) 45 else 0, hjust=if (compare) 1 else 0.5),
              axis.title=element_text(size=11),
              plot.title=element_text(size=14, face="bold", hjust=0.5),
              plot.margin=margin(10, 20, 20, 10))
}
units <- list()
for (i in seq_along(m$cells)) {
    cell <- m$cells[[i]]
    comparing <- m$mode == "compare"
    relative_dir <- file.path(if (comparing) "enrichment_compare" else "enrichment", cell$key)
    directory <- file.path(out, relative_dir)
    dir.create(directory, recursive=TRUE, showWarnings=FALSE)
    prefix <- sprintf("GO.%sBP.qval%s_pval%s", if (comparing) "cmp." else "", m$qvalue, m$pvalue)
    png_path <- file.path(directory, paste0(prefix, ".png"))
    csv_path <- file.path(directory, paste0(prefix, ".csv"))
    genes <- read_genes(cell$input)
    cluster_counts <- list()
    if (length(genes)) {
        if (comparing) {
            gene_ls <- lapply(cell$cluster_inputs, function(x) read_genes(x$path))
            names(gene_ls) <- vapply(cell$cluster_inputs, function(x) x$label, character(1))
            cluster_counts <- as.list(vapply(gene_ls, length, integer(1)))
            # Ordinary annotation/version warnings must not discard the result.
            if (any(lengths(gene_ls))) {
                result <- compareCluster(gene_ls, fun="enrichGO", pvalueCutoff=m$pvalue,
                    qvalueCutoff=m$qvalue, OrgDb=org, ont="BP", keyType="ENSEMBL", readable=TRUE)
            } else result <- NULL
        } else {
            result <- enrichGO(gene=genes, keyType="ENSEMBL", OrgDb=org, ont="BP",
                pAdjustMethod="BH", pvalueCutoff=m$pvalue, qvalueCutoff=m$qvalue,
                readable=TRUE, pool=FALSE)
        }
    } else result <- NULL
    rows <- if (is.null(result)) data.frame() else as.data.frame(result)
    if (!nrow(rows)) {
        rows <- data.frame(ID=character(), Description=character(), GeneRatio=character(),
            BgRatio=character(), pvalue=numeric(), p.adjust=numeric(), qvalue=numeric(),
            geneID=character(), Count=integer())
    }
    write.csv(rows, csv_path)
    status <- if (cell$missing) "missing_input" else if (!length(genes)) "no_significant_events" else if (!nrow(rows)) "no_enrichment" else "completed"
    images <- list(file.path(relative_dir, paste0(prefix, ".png")))
    files <- c(images, list(file.path(relative_dir, paste0(prefix, ".csv"))))
    warning_messages <- list()
    if (nrow(rows)) {
        p <- dotplot(result, showCategory=15, title=if (comparing) "GO_BP" else "BP")
        save_fig(style_plot(p, comparing), png_path, format="png",
                 width=if (comparing) 14 else 6, height=if (comparing) 10 else 6)
        if (!comparing && isTRUE(m$simple)) {
            # GO_similarity / binary_cut are unchanged from ASTK --simple.
            # Save primary outputs first and draw the heatmap just once.
            tryCatch({
                simdir <- file.path(directory, "simgo")
                dir.create(simdir, showWarnings=FALSE)
                emat <- simplifyEnrichment::GO_similarity(result$ID, "BP")
                clusters <- simplifyEnrichment::simplifyGO(emat, plot=FALSE)
                ps <- simplifyEnrichment::ht_clusters(emat, clusters$cluster,
                    column_title=sprintf("%s GO terms clustered by binary_cut", nrow(emat)))
                simp <- file.path(simdir, "GO_BP_simple.png")
                png(simp, width=12, height=10, units="in", res=72)
                tryCatch(ComplexHeatmap::draw(ps), finally=dev.off())
                write.csv(clusters, file.path(simdir, "GO_BP_simple.csv"))
                images <- c(images, list(file.path(relative_dir, "simgo/GO_BP_simple.png")))
                files <- c(files, list(file.path(relative_dir, "simgo/GO_BP_simple.png"),
                                      file.path(relative_dir, "simgo/GO_BP_simple.csv")))
            }, error=function(e) {
                warning_messages <<- c(warning_messages, list(paste("GO clustering:", conditionMessage(e))))
                message("Optional GO clustering failed: ", conditionMessage(e))
            })
        }
    } else {
        empty_plot(png_path, switch(status, missing_input="Input file missing",
            no_significant_events="No significant AS events in this subset",
            "No GO BP terms pass ASTK p / adjusted-p / q cutoffs"))
    }
    cell$status <- status
    cell$terms <- nrow(rows)
    cell$cluster_gene_counts <- cluster_counts
    cell$images <- images
    cell$files <- files
    cell$tables <- list(file.path(relative_dir, paste0(prefix, ".csv")))
    cell$warnings <- warning_messages
    units[[i]] <- cell
    write_json_atomic(list(done=i, total=length(m$cells)), file.path(out, "native_progress.json"))
}
versions <- c("clusterProfiler", "enrichplot", "GO.db", org_name, "qvalue", "simplifyEnrichment")
provenance <- list(R=R.version.string, packages=setNames(lapply(versions, function(p)
    if (requireNamespace(p, quietly=TRUE)) as.character(packageVersion(p)) else NA_character_), versions),
    ontology="BP", key_type="ENSEMBL", background="OrgDb default GO BP universe",
    p_adjust_method="BH", pvalue=m$pvalue, qvalue=m$qvalue,
    length_breaks=m$length_breaks, random_seed=1, astk_utils=m$astk_utils)
write_json_atomic(list(units=units, provenance=provenance), file.path(out, "native_results.json"))
