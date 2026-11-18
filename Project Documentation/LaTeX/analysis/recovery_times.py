import pandas as pd, numpy as np, glob, os
rec = []
for f in sorted(glob.glob("results/*.csv")):
    d = pd.read_csv(f)
    if len(d) < 10: continue
    d["dt"] = d.ts.diff(); d["ep"] = (d["mode"] != d["mode"].shift()).cumsum()
    eps = [(e, g) for e, g in d.groupby("ep")]
    for (e1, g1), (e2, g2) in zip(eps, eps[1:]):
        if g1["mode"].iloc[0] == "attack" and g2["mode"].iloc[0] in ("protected", "normal", "idle") and len(g1) >= 8:
            t0 = g2.ts.iloc[0]
            ok = g2[(g2.resp_avg_ms < 120) & (g2.failed < 3) & (g2.db_qps < 22)]
            # require 2 consecutive healthy ticks
            t = None
            idx = list(g2.index)
            for i in range(len(idx) - 1):
                a, b = g2.loc[idx[i]], g2.loc[idx[i + 1]]
                if all(x.resp_avg_ms < 120 and x.failed < 3 and x.db_qps < 22 for x in (a, b)):
                    t = a.ts - t0; break
            rec.append(dict(file=os.path.basename(f)[8:23], to=g2["mode"].iloc[0], t=None if t is None else round(t, 2)))
R = pd.DataFrame(rec)
print(R.to_string())
for to, g in R.groupby("to"):
    v = g.t.dropna()
    print(to, len(g), "recovered", len(v), "median", v.median(), "p75", v.quantile(.75), "max", v.max())
fin = R[R.file == "20261022_165810"]
for to, g in fin.groupby("to"):
    v = g.t.dropna(); print("FINAL", to, len(g), len(v), v.median(), v.max())
