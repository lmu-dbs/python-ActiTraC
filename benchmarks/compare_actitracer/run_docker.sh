#!/bin/bash
# Run actitraceR, the port and this package with the same hash seeds. Run inside the
# container, with the repository at /repo and the logs in the volume at /data/logs
# (benchmarks/docker/run.sh downloads them):
#
#   docker build -t actitrac-r benchmarks/compare_actitracer
#   docker run --name actitrac-r -v actitrac-data:/data -v "$PWD":/repo:ro actitrac-r \
#       bash benchmarks/compare_actitracer/run_docker.sh
#
# Results go to /data/r_out. summarize.py turns them into tables.
set -u
export HERE=/repo/benchmarks/compare_actitracer
export LIMIT=${LIMIT:-10800} TZ=UTC
JOBS=${JOBS:-16}
mkdir -p /data/r_out
cd /data/r_out || exit 1

R --version | head -1
python --version
pip list 2>/dev/null | grep -E '^(pm4py|numpy|pandas|scipy) '
cat /opt/r_src/commits.txt

python "$HERE/make_csv.py" /data/logs Helpdesk Sepsis BPIC13_closedproblems
Rscript "$HERE/dump_r.R" Helpdesk Sepsis > dump.log 2>&1
Rscript "$HERE/defects.R" 2>&1 | grep -av 'Clustering traces' > defects.log
python "$HERE/silent_moves.py" > silent_moves.log 2>&1

run_job() {
    tool=$1; tag=$2; seed=$3; shift 3
    base="${tool}_${tag}_s${seed}"
    export PYTHONHASHSEED=$seed
    case $tool in
        r) timeout "$LIMIT" Rscript "$HERE/run_r.R" "$@" "$base.csv" 2>&1 | grep -av 'Clustering traces' > "$base.log"
           status=${PIPESTATUS[0]} ;;
        port) name=$1; k=$2; target=$3; mcs=$4; noise=$5; shift 5
           timeout "$LIMIT" python "$HERE/port.py" "$name" "$k" "$target" "$mcs" "$noise" "$base.csv" "$@" > "$base.log" 2>&1
           status=$? ;;
        package) timeout "$LIMIT" python "$HERE/run_package.py" "$@" "$base.csv" > "$base.log" 2>&1
           status=$? ;;
    esac
    # A progress bar cut off by the time limit leaves no line break, so add one.
    printf '\nstatus %s\n' "$status" >> "$base.log"
    echo "$base status $status"
}
export -f run_job

jobs_file=$(mktemp)
ALL="dist=act fit=pkg mcs=start seed=force look=always resid=pkg feed=pkg order=pkg"
for seed in 0 1 2 3; do
    # actitraceR, at the three windows that show it ignores the window, then the other settings.
    {
        echo "r w0 $seed Helpdesk 4 0.99 0.25 0 0.2"
        echo "r w25 $seed Helpdesk 4 0.99 0.25 0.25 0.2"
        echo "r w1 $seed Helpdesk 4 0.99 0.25 1 0.2"
        echo "r t95 $seed Helpdesk 4 0.95 0.25 0.25 0.2"
        echo "r mcs60 $seed Helpdesk 4 0.99 0.6 0.25 0.2"
        echo "r t1 $seed Helpdesk 4 1.0 0.25 0.25 0.2"
        echo "r noise0 $seed Helpdesk 4 1.0 0.25 0.25 0"
        # The port, on the same settings.
        echo "port base $seed Helpdesk 4 0.99 0.25 0.2"
        echo "port t95 $seed Helpdesk 4 0.95 0.25 0.2"
        echo "port mcs60 $seed Helpdesk 4 0.99 0.6 0.2"
        echo "port t1 $seed Helpdesk 4 1.0 0.25 0.2"
        echo "port noise0 $seed Helpdesk 4 1.0 0.25 0"
        # One difference at a time, then all of them.
        for flag in look=always dist=act mcs=start fit=pkg feed=pkg order=pkg resid=pkg seed=force; do
            echo "port ${flag%%=*} $seed Helpdesk 4 0.99 0.25 0.2 $flag"
        done
        echo "port all $seed Helpdesk 4 0.99 0.25 0.2 $ALL"
        # This package, at window 0.25 and at window 1, the closest match to a window that is ignored.
        for window in 0.25 1; do
            tag=w${window/0./}
            echo "package ${tag} $seed Helpdesk 4 0.99 0.25 $window 0.2"
            echo "package t95_${tag} $seed Helpdesk 4 0.95 0.25 $window 0.2"
            echo "package mcs60_${tag} $seed Helpdesk 4 0.99 0.6 $window 0.2"
            echo "package t1_${tag} $seed Helpdesk 4 1.0 0.25 $window 0.2"
            echo "package noise0_${tag} $seed Helpdesk 4 1.0 0.25 $window 0"
        done
    } >> "$jobs_file"
done
echo "r closed 0 BPIC13_closedproblems 5 1.0 0.25 0.25 0.2" >> "$jobs_file"
for seed in 0 1; do
    {
        echo "port sep_t99 $seed Sepsis 6 0.99 0.25 0.2"
        echo "port sep_t1 $seed Sepsis 6 1.0 0.25 0.2"
        for window in 0.25 1; do
            tag=w${window/0./}
            echo "package sep_t99_${tag} $seed Sepsis 6 0.99 0.25 $window 0.2"
            echo "package sep_t1_${tag} $seed Sepsis 6 1.0 0.25 $window 0.2"
        done
        echo "r sep_t99 $seed Sepsis 6 0.99 0.25 0.25 0.2"
        echo "r sep_t1 $seed Sepsis 6 1.0 0.25 0.25 0.2"
    } >> "$jobs_file"
done
xargs -P "$JOBS" -L 1 bash -c 'run_job "$0" "$@"' < "$jobs_file"
rm -f "$jobs_file"
echo finished
