# Run actitraceR on a log, in the working directory.
#   Rscript run_r.R NAME K TARGET MCS WINDOW NOISE OUT.csv
# NAME.csv has the columns case, activity, timestamp, lifecycle. OUT.csv gets case, cluster.
# discover_pm does not forward `...`, so the noise threshold goes in through a wrapper.
# The final evaluation can run for hours, so OUT.csv is written just before it starts.
# That adds one statement to cluster_traces and leaves the clustering as it is. With
# ACTITRACER_EVALUATE=0 in the environment, the run ends there.
args <- commandArgs(TRUE)
name <- args[1]; k <- as.integer(args[2]); target <- as.numeric(args[3]); mcs <- as.numeric(args[4]); win <- as.numeric(args[5]); noise <- as.numeric(args[6]); out <- args[7]
suppressPackageStartupMessages({library(bupaR); library(dplyr); library(actitraceR)})
d <- read.csv(paste0(name, ".csv"), stringsAsFactors = FALSE, na.strings = character(), colClasses = c(case = "character"))
d$timestamp <- as.POSIXct(d$timestamp, tz = "UTC")
d <- d %>% mutate(instance = row_number(), resource = "r")
log <- eventlog(d, case_id = "case", activity_id = "activity", activity_instance_id = "instance",
                lifecycle_id = "lifecycle", timestamp = "timestamp", resource_id = "resource")
algo <- function(log, convert = TRUE) pm4py::discover_inductive(log, noise_threshold = noise, convert = convert)
t0 <- Sys.time()
elapsed <- function() as.numeric(difftime(Sys.time(), t0, units = "secs"))
save_labels <- function(r) {
  res <- bind_rows(lapply(seq_along(r), function(i) data.frame(case = unique(r[[i]]$case), cluster = i - 1L)))
  write.csv(res, out, row.names = FALSE)
  cat("labels:", sapply(r, function(x) n_cases(x)), " seconds:", elapsed(), "\n")
}
clusterer <- actitraceR::cluster_traces
code <- body(clusterer)
at <- which(vapply(as.list(code), function(x) identical(deparse(x)[1], 'cli::cli_alert_info("Evaluating clusters")'), TRUE))
stopifnot(length(at) == 1)
code[[at]] <- if (Sys.getenv("ACTITRACER_EVALUATE") == "0") {
  bquote({ .(save_labels)(logs_list); return(logs_list) })
} else {
  bquote({ .(save_labels)(logs_list); .(code[[at]]) })
}
# actitraceR stops with an error when a cluster ends up empty. With ACTITRACER_DROP_EMPTY=1,
# empty clusters go before the residual step. With no cluster left, the rest forms one.
if (Sys.getenv("ACTITRACER_DROP_EMPTY") == "1") {
  at <- which(vapply(as.list(code), function(x) identical(deparse(x)[1], "if (nrow(R) > 0) {"), TRUE))
  stopifnot(length(at) == 1)
  code[[at]] <- bquote({
    CS <- Filter(function(x) nrow(x) > 0, CS)
    if (length(CS) == 0) { CS <- list(R); R <- R[0, ] }
    .(code[[at]])
  })
}
body(clusterer) <- code
r <- clusterer(log, number_of_clusters = k, target_fitness = target, minimal_cluster_size = mcs,
               window_size = win, discover_algorithm = algo)
cat("sizes:", sapply(r, function(x) n_cases(x)), " seconds:", elapsed(), "\n")
