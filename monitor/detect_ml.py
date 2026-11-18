"""ML-based detector (unsupervised anomaly detection).

An IsolationForest is trained ONLY on normal-baseline samples (traffic on, no
attack). After training, each live sample gets an anomaly score; a score past the
threshold means "this does not look like normal traffic" -> attack. No manual
labelling is needed, which is why this suits a beginner project.

The report can then compare this detector against the rule-based one (detection
time, false alarms).
"""
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

FEATURES = ["db_qps", "resp_avg_ms", "miss_rate", "rps", "failed"]
MIN_TRAIN = 10          # baseline samples needed before we can train (~5s at 2Hz)


class MLDetector:
    """Standardizes features first, so every signal contributes equally, then uses
    an IsolationForest trained on normal traffic. An attack lands many standard
    deviations away on db load / latency / failures, so it is flagged reliably.
    """

    def __init__(self):
        self._baseline = []
        self._scaler = None
        self._model = None

    def observe_baseline(self, sample):
        """Collect a normal sample; (re)train once we have enough."""
        self._baseline.append([sample[f] for f in FEATURES])
        if len(self._baseline) >= MIN_TRAIN:
            self._baseline = self._baseline[-300:]   # keep the window bounded
            data = np.array(self._baseline, dtype=float)
            self._scaler = StandardScaler().fit(data)
            self._model = IsolationForest(contamination=0.01, random_state=0)
            self._model.fit(self._scaler.transform(data))

    @property
    def ready(self):
        return self._model is not None

    def score(self, sample):
        """Return (normalized_score 0..1, is_anomaly). 0.08 when not trained yet.

        The alert uses the model's own outlier decision (predict == -1), calibrated
        by the training data. The normalized score is only for the dashboard gauge.
        """
        if self._model is None:
            return 0.08, False
        x = self._scaler.transform([[sample[f] for f in FEATURES]])
        raw = float(self._model.decision_function(x)[0])   # +normal / -anomaly
        is_anomaly = self._model.predict(x)[0] == -1
        norm = max(0.0, min(1.0, 0.5 - raw * 4.0))         # spread for a readable gauge
        return norm, bool(is_anomaly)
