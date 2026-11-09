# Environment for benchmarks/compare_entropic.py and the test suite, on the pm4py
# version the paper used, and a JDK for benchmarks/prom_emulation. The repository is
# mounted at run time. See run.sh.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "pm4py==2.7.8.4" pytest
ENV PYTHONPATH=/repo/src PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /repo
