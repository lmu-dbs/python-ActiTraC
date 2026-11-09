# Write actitraceR's variant order and case map for replica.py.
#   Rscript dump_r.R NAME [NAME ...]
suppressPackageStartupMessages({library(bupaR); library(dplyr); library(actitraceR)})
for (name in commandArgs(TRUE)) {
d <- read.csv(paste0(name,".csv"), stringsAsFactors=FALSE, na.strings=character(), colClasses=c(case="character"))
d$timestamp <- as.POSIXct(d$timestamp, tz="UTC"); d <- d %>% mutate(instance=row_number(), resource="r")
log <- eventlog(d, case_id="case", activity_id="activity", activity_instance_id="instance", lifecycle_id="lifecycle", timestamp="timestamp", resource_id="resource")
log[[activity_id(log)]] <- as.character(log[[activity_id(log)]]); log <- log[log[[lifecycle_id(log)]] == "complete", ]
dict <- actitraceR:::get_dict(log); tt <- actitraceR:::get_tokenized_traces(log, dict)
write.csv(data.frame(trace_id=as.character(tt$trace_id), freq=tt$absolute_frequency, tokens=sapply(tt$tokens, paste, collapse="")), paste0("dump_",name,"_var.csv"), row.names=FALSE)
cl <- log %>% case_list(.keep_trace_list=FALSE) %>% as.data.frame() %>% select(case, trace_id)
write.csv(cl, paste0("dump_",name,"_case.csv"), row.names=FALSE)
}
