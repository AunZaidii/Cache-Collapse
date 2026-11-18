"""CSV logger: writes one row of metrics every second.

The file is both the detectors' raw input and the data for the report graphs
(pandas / matplotlib). A new file is started each time the monitor boots.
"""
import os
import csv
import time

COLUMNS = [
    "ts", "mode", "rps", "db_qps", "cache_hits", "cache_misses", "hit_rate",
    "resp_avg_ms", "resp_p95_ms", "failed", "rule_alert", "ml_score", "ml_alert",
]


class CsvLogger:
    def __init__(self, folder="/app/data"):
        os.makedirs(folder, exist_ok=True)
        name = "metrics_%s.csv" % time.strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(folder, name)
        self._f = open(self.path, "w", newline="")
        self._w = csv.DictWriter(self._f, fieldnames=COLUMNS)
        self._w.writeheader()
        self._f.flush()

    def write(self, row):
        self._w.writerow({k: row.get(k, "") for k in COLUMNS})
        self._f.flush()
