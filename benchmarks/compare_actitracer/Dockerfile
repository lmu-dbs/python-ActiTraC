# Environment for the actitraceR comparison: R 4.3 and the pm4py version its wrapper
# pins (2.7.2). The repository is mounted at run time. See run_docker.sh.
FROM condaforge/miniforge3:24.11.3-2
RUN mamba create -y -q -p /opt/renv -c conda-forge --override-channels \
        r-base=4.3 python=3.10 pip git make compilers r-remotes r-reticulate \
        r-dplyr r-tidyr r-purrr r-stringr r-stringdist r-glue r-cli r-magrittr r-rlang \
        r-tibble r-stringi r-uuid r-xml2 r-rvest r-dt r-huxtable r-igraph r-rstudioapi \
        r-diagrammer r-diagrammersvg r-visnetwork r-htmlwidgets r-lubridate r-ggplot2 \
        r-hms r-zoo r-data.table r-shiny r-miniui r-readr r-forcats r-scales r-ggthemes \
        r-ggdendro r-pheatmap r-progress r-plotly r-patchwork \
    && mamba clean -afy
ENV PATH=/opt/renv/bin:$PATH RETICULATE_PYTHON=/opt/renv/bin/python \
    PYTHONPATH=/repo/src PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
RUN pip install --no-cache-dir "pm4py==2.7.2"
# bupaR and edeaR are not on conda-forge, and the others are only on GitHub.
RUN Rscript -e 'install.packages(c("bupaR", "edeaR"), repos = "https://cloud.r-project.org", Ncpus = 8); stopifnot(all(c("bupaR", "edeaR") %in% rownames(installed.packages())))'
RUN mkdir /opt/r_src && cd /opt/r_src \
    && for package in petrinetR bpmnR pm4py actitraceR; do \
           git clone -q --depth 1 "https://github.com/bupaverse/$package" "$package" \
           && git -C "$package" log -1 --format="$package %h %ad" --date=short >> /opt/r_src/commits.txt \
           && R CMD INSTALL --no-docs --no-test-load "$package" || exit 1; \
       done
WORKDIR /repo
