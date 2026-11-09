"""Download the paper's logs from 4TU.ResearchData, named as compare_entropic.py expects.

Usage: python fetch_logs.py DIRECTORY
"""
import json
import os
import sys
import urllib.request

DATASETS = {
    "Helpdesk": 12675977,
    "RTFM": 12683249,
    "BPIC12": 12689204,
    "BPIC13_incidents": 12693914,
    "BPIC13_closedproblems": 12714476,
    "Hospital_Billing": 12705113,
    "Sepsis": 12707639,
    "BPIC15_1": 12709154,
    "BPIC15_2": 12697349,
    "BPIC15_3": 12718370,
    "BPIC15_4": 12697898,
    "BPIC15_5": 12713285,
}
HEADERS = {"User-Agent": "python-actitrac-validation"}


def fetch(url, timeout):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


def main(directory):
    os.makedirs(directory, exist_ok=True)
    for name, article in DATASETS.items():
        with fetch(f"https://data.4tu.nl/v2/articles/{article}/files", 60) as response:
            files = json.load(response)
        for file in files:
            for extension in (".xes.gz", ".xes", ".csv"):
                if file["name"].endswith(extension):
                    path = os.path.join(directory, name + extension)
                    with fetch(file["download_url"], 600) as response, open(path, "wb") as out:
                        out.write(response.read())
                    print(name, file["name"], os.path.getsize(path), "of", file["size"], flush=True)
                    break


if __name__ == "__main__":
    main(sys.argv[1])
