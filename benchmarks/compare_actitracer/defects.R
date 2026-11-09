# Checks of actitraceR's defects on Helpdesk, in the working directory. See docs/fidelity.md.
suppressPackageStartupMessages({library(bupaR); library(dplyr); library(actitraceR); library(stringdist)})
d <- read.csv("Helpdesk.csv", stringsAsFactors = FALSE, na.strings = character(), colClasses = c(case = "character"))
d$timestamp <- as.POSIXct(d$timestamp, tz = "UTC")
d <- d %>% mutate(instance = row_number(), resource = "r")
log <- eventlog(d, case_id = "case", activity_id = "activity", activity_instance_id = "instance",
                lifecycle_id = "lifecycle", timestamp = "timestamp", resource_id = "resource")
dict <- actitraceR:::get_dict(log)
traces <- actitraceR:::get_tokenized_traces(log, dict)
cat("variants", nrow(traces), "relative_frequency range", range(traces$relative_frequency),
    "grouped by", paste(group_vars(traces), collapse = ","), "\n")
for (window in c(0, .25, 1)) {
  cat("window", window, "rows", nrow(actitraceR:::get_window_traces(traces, data.frame(), window)), "\n")
}
cat("mra exists:", exists("mra", asNamespace("actitraceR")), "\n")
result <- tryCatch(cluster_traces(log, number_of_clusters = 2, distance_metric = mra()),
                   error = function(e) conditionMessage(e))
cat("mra call:", if (is.character(result)) result[1] else "ran", "\n")
osa <- function(a, b) stringdist(a, b, method = "osa")
cat("insert [3]:", osa("[1][2]", "[1][2][3]"), " insert [13]:", osa("[1][2]", "[1][2][13]"),
    " replace [2] with [12]:", osa("[1][2]", "[1][12]"), "\n")
