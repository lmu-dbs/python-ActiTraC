#!/bin/bash
# The six logs run_docker.sh leaves out, as in that script, after it. Results go to the
# same /data/r_out. actitraceR's final evaluation is left out, because it adds hours and
# does not change the clusters. Empty clusters are dropped, because they stop actitraceR
# with an error. Logs run from smallest to largest, and finished jobs are skipped.
set -u
export HERE=/repo/benchmarks/compare_actitracer
export LIMIT=${LIMIT:-43200} TZ=UTC ACTITRACER_EVALUATE=0 ACTITRACER_DROP_EMPTY=1
JOBS=${JOBS:-32}
SMALL="BPIC13_closedproblems:5 BPIC13_incidents:5"
LARGE="RTFM:4 Hospital_Billing:5 BPIC12:4 BPIC15:4"
mkdir -p /data/r_out
cd /data/r_out || exit 1

names=$(for entry in $SMALL $LARGE; do echo "${entry%%:*}"; done)
python "$HERE/make_csv.py" /data/logs $names 2>/dev/null
Rscript "$HERE/dump_r.R" $names > dump_rest.log 2>&1
echo "dump status $?"

run_job() {
    tool=$1; tag=$2; seed=$3; shift 3
    base="${tool}_${tag}_s${seed}"
    if grep -aqs '^status 0' "$base.log"; then echo "$base done"; return; fi
    export PYTHONHASHSEED=$seed
    case $tool in
        r) timeout "$LIMIT" Rscript "$HERE/run_r.R" "$@" "$base.csv" 2>&1 | grep -av 'Clustering traces' > "$base.log"
           status=${PIPESTATUS[0]} ;;
        replica) name=$1; k=$2; target=$3; mcs=$4; noise=$5; shift 5
           timeout "$LIMIT" python "$HERE/replica.py" "$name" "$k" "$target" "$mcs" "$noise" "$base.csv" "$@" > "$base.log" 2>&1
           status=$? ;;
        pyactitrac) timeout "$LIMIT" python "$HERE/run_pyactitrac.py" "$@" "$base.csv" > "$base.log" 2>&1
           status=$? ;;
        evaluation) timeout "$LIMIT" python "$HERE/evaluation_time.py" "$@" > "$base.log" 2>&1
           status=$? ;;
    esac
    # A progress bar cut off by the time limit leaves no line break, so add one.
    printf '\nstatus %s\n' "$status" >> "$base.log"
    echo "$base status $status"
}
export -f run_job

jobs_file=$(mktemp)
{
    # What the logs do unchanged.
    echo "r raw_BPIC13_closedproblems 0 BPIC13_closedproblems_raw 5 1.0 0.25 0.25 0.2"
    echo "r raw_BPIC13_incidents 0 BPIC13_incidents_raw 5 1.0 0.25 0.25 0.2"
    echo "r raw_BPIC12 0 BPIC12_raw 4 1.0 0.25 0.25 0.2"
    # Which step of the final evaluation does not finish on Sepsis.
    echo "evaluation sep_clusters 0 Sepsis r_sep_t1_s0.csv 0.2 clusters"
    echo "evaluation sep_whole 0 Sepsis r_sep_t1_s0.csv 0.2 whole"
    for entry in $SMALL $LARGE; do
        name=${entry%%:*}; k=${entry##*:}
        for seed in 0 1; do
            for target in 1.0 0.99; do
                tag="${name}_t${target/./}"
                echo "replica $tag $seed $name $k $target 0.25 0.2 empty=drop"
                echo "pyactitrac ${tag}_w25 $seed $name $k $target 0.25 0.25 0.2"
                echo "pyactitrac ${tag}_w1 $seed $name $k $target 0.25 1 0.2"
                echo "r $tag $seed $name $k $target 0.25 0.25 0.2"
            done
        done
    done
} > "$jobs_file"
xargs -P "$JOBS" -L 1 bash -c 'run_job "$0" "$@"' < "$jobs_file"
rm -f "$jobs_file"
echo finished
