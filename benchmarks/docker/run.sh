#!/bin/bash
# Fetch the data, run the tests, and run the benchmark in both modes. Run inside the
# container, with the repository at /repo and a volume at /data:
#
#   docker build -t actitrac-bench benchmarks/docker
#   docker run --name actitrac-bench -v actitrac-data:/data -v "$PWD":/repo:ro actitrac-bench \
#       bash benchmarks/docker/run.sh
#
# Results go to /data/out.
set -u
RESULTS=/data/entropic/experiment/experimental_results_one_cluster_size/results
LOGS="Helpdesk RTFM BPIC13_incidents BPIC13_closedproblems Hospital_Billing Sepsis BPIC12 BPIC15"
JOBS=${JOBS:-16}
mkdir -p /data/out/default /data/out/prom_compatible

[ -f /data/logs/BPIC15_5.xes ] || python benchmarks/docker/fetch_logs.py /data/logs
[ -d /data/entropic/.git ] || git clone -q --depth 1 https://github.com/jaripeeperkorn/EntropicClustering /data/entropic
git -C /data/entropic log -1 --format='EntropicClustering %h %ad' --date=short
pip list 2>/dev/null | grep -E '^(pm4py|numpy|pandas|scipy) '

ACTITRAC_HELPDESK_CSV=/data/logs/Helpdesk.csv python -m pytest -q -p no:cacheprovider 2>&1 | tail -15

bench() {
    python benchmarks/compare_entropic.py --data /data/logs --results "$RESULTS" --logs "$2" ${3:-} \
        > "/data/out/$1/$2.out" 2> "/data/out/$1/$2.err"
    echo "$1 $2 exit $?"
}
export -f bench
export RESULTS
for log in $LOGS; do
    echo "default $log"
    echo "prom_compatible $log --prom-compatible"
done | xargs -P "$JOBS" -L 1 bash -c 'if [ "$0" = default ]; then bench default "$1"; else bench prom_compatible "$1" "$2"; fi'
echo finished
