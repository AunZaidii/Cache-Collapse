import pandas as pd, numpy as np, glob, os, json, sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, roc_curve

SP = sys.argv[1]
OUT = "Project Documentation/LaTeX/figures"
os.makedirs(OUT, exist_ok=True)
C = {"normal": "#2a78d6", "attack": "#eb6834", "protected": "#1baf7a", "idle": "#898781", "x": "#eda100"}
INK = "#0b0b0b"; MUTED = "#52514e"; GRID = "#e1e0d9"
plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.6, "legend.frameon": False,
    "savefig.bbox": "tight", "pdf.fonttype": 42})
S = {}
LBL = {"normal": "Normal", "attack": "Undefended attack", "protected": "Defended attack"}


def load(f):
    d = pd.read_csv(f); d["dt"] = d.ts.diff()
    d["file"] = os.path.basename(f)[8:23]
    d["ep"] = (d["mode"] != d["mode"].shift()).cumsum()
    d["fail_s"] = d.failed / d.dt
    tot = d.cache_hits + d.cache_misses
    d["miss_rate"] = np.where(tot > 0, d.cache_misses / tot.replace(0, np.nan), 0.0)
    d["db_n"] = d.db_qps * d.dt
    d["ml_ready"] = ~((d.ml_score == 0.08) & (d.ml_alert == 0))
    return d


files = sorted(glob.glob("results/*.csv"))
ALL = pd.concat([load(f) for f in files if os.path.getsize(f) > 200], ignore_index=True)
ALL["valid"] = (ALL.dt > 0.25) & (ALL.dt < 2.0)
S["dataset"] = {"files": len(files), "rows": int(len(ALL)), "valid_rows": int(ALL.valid.sum()),
    "hours": round(ALL.groupby("file").ts.agg(lambda x: x.iloc[-1] - x.iloc[0]).sum() / 3600, 1),
    "mode_rows": ALL["mode"].value_counts().to_dict()}
FINAL = "20261022_165810"
F = ALL[(ALL.file == FINAL) & ALL.valid].copy()
S["final"] = {"rows": int(len(F)), "mode_rows": F["mode"].value_counts().to_dict(), "tick_median": round(F.dt.median(), 3)}


def q(x, p): return float(np.nanpercentile(x, p))


tab = {}
for m in ["idle", "normal", "attack", "protected"]:
    g = F[F["mode"] == m]; r = {}
    for col in ["rps", "db_qps", "resp_avg_ms", "resp_p95_ms", "fail_s", "miss_rate"]:
        r[col] = dict(med=round(q(g[col], 50), 2), p25=round(q(g[col], 25), 2), p75=round(q(g[col], 75), 2),
                      p95=round(q(g[col], 95), 2), max=round(float(g[col].max()), 2), mean=round(float(g[col].mean()), 2))
    r["n"] = int(len(g))
    r["coalesce_misses_per_db"] = round(g.cache_misses.sum() / max(g.db_n.sum(), 1e-9), 2)
    r["db_attempts"] = round(g.db_n.sum()); r["misses"] = int(g.cache_misses.sum()); r["fails"] = int(g.failed.sum())
    r["completed_db_per_s_med"] = round(q((g.db_n - g.failed).clip(lower=0) / g.dt, 50), 2)
    r["frac_ticks_with_fail"] = round(float((g.failed > 0).mean()), 3)
    tab[m] = r
S["modes"] = tab

rng = np.random.default_rng(0)


def boot_ratio(a, b, n=2000):
    a = a.values; b = b.values; rs = []
    for _ in range(n):
        rs.append(np.median(rng.choice(a, len(a))) / max(np.median(rng.choice(b, len(b))), 1e-9))
    return [round(np.percentile(rs, 2.5), 1), round(np.percentile(rs, 97.5), 1)]


A = F[F["mode"] == "attack"]; P = F[F["mode"] == "protected"]; N = F[F["mode"] == "normal"]
S["ratios"] = {"db_med_attack_over_protected": round(A.db_qps.median() / P.db_qps.median(), 1),
    "db_ci": boot_ratio(A.db_qps, P.db_qps),
    "db_med_attack_over_normal": round(A.db_qps.median() / N.db_qps.median(), 1),
    "db_peak_attack_over_normal_med": round(A.db_qps.max() / N.db_qps.median(), 1),
    "resp_med_attack_over_protected": round(A.resp_avg_ms.median() / P.resp_avg_ms.median(), 1),
    "resp_ci": boot_ratio(A.resp_avg_ms, P.resp_avg_ms),
    "db_mean_attack_over_protected": round(A.db_qps.mean() / P.db_qps.mean(), 1)}

# episodes
eps = []
for ep, g in ALL[ALL.file == FINAL].groupby("ep"):
    m = g["mode"].iloc[0]
    if m == "idle" or len(g) < 8: continue
    t0 = g.ts.iloc[0]

    def first(c):
        x = g[g[c] == 1]; return round(float(x.ts.iloc[0] - t0), 1) if len(x) else None
    gv = g[g.valid]
    eps.append(dict(mode=m, n=len(g), dur=round(float(g.ts.iloc[-1] - t0), 1), rule_t=first("rule_alert"), ml_t=first("ml_alert"),
        ml_ready=bool(g.ml_ready.iloc[0]), rule_frac=round(float(g.rule_alert.mean()), 2), ml_frac=round(float(g.ml_alert.mean()), 2),
        db_med=float(gv.db_qps.median()), resp_med=float(gv.resp_avg_ms.median()), fail_med=round(float(gv.fail_s.median()), 1)))
E = pd.DataFrame(eps); E.to_csv(SP + "/final_eps.csv", index=False)
ea = E[E["mode"] == "attack"]
S["episodes"] = {"attack_n": int(len(ea)), "protected_n": int((E["mode"] == "protected").sum()), "normal_n": int((E["mode"] == "normal").sum()),
    "rule_detected": int(ea.rule_t.notna().sum()), "ml_detected": int(ea.ml_t.notna().sum()), "ml_ready_eps": int(ea.ml_ready.sum()),
    "either_detected": int((ea.rule_t.notna() | ea.ml_t.notna()).sum()),
    "rule_t_med": float(ea.rule_t.median()), "rule_t_iqr": [float(ea.rule_t.quantile(.25)), float(ea.rule_t.quantile(.75))], "rule_t_max": float(ea.rule_t.max()),
    "ml_t_med": float(ea.ml_t.median()), "ml_t_iqr": [float(ea.ml_t.quantile(.25)), float(ea.ml_t.quantile(.75))], "ml_t_max": float(ea.ml_t.max()),
    "either_t_med": float(ea[["rule_t", "ml_t"]].min(axis=1).median()),
    "rule_cov_med": float(ea.rule_frac.median()), "ml_cov_med": float(ea.ml_frac.median())}


def cm(pred, truth):
    pred = np.asarray(pred, bool); truth = np.asarray(truth, bool)
    tp = int((pred & truth).sum()); fp = int((pred & ~truth).sum()); fn = int((~pred & truth).sum()); tn = int((~pred & ~truth).sum())
    pr = tp / (tp + fp) if tp + fp else 0; rc = tp / (tp + fn) if tp + fn else 0
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=round(pr, 3), recall=round(rc, 3),
                f1=round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0, fpr=round(fp / (fp + tn), 4) if fp + tn else 0)


AN = F[F["mode"].isin(["attack", "normal"])]
truth = (AN["mode"] == "attack").values
ANr = AN[AN.ml_ready]
S["tick"] = {"rule": cm(AN.rule_alert.values == 1, truth), "ml": cm(AN.ml_alert.values == 1, truth),
    "ml_readyonly": cm(ANr.ml_alert.values == 1, (ANr["mode"] == "attack").values),
    "either": cm((AN.rule_alert.values == 1) | (AN.ml_alert.values == 1), truth),
    "alert_rate": {m: {"rule": round(float(F[F["mode"] == m].rule_alert.mean()), 4), "ml": round(float(F[F["mode"] == m].ml_alert.mean()), 4)} for m in ["idle", "normal", "attack", "protected"]}}

base = max(N.db_qps.median(), 5); S["rule_base"] = float(base)
grid = []
for K in [2, 3, 5, 8, 12]:
    for tl in [100, 150, 200, 300]:
        for tm in [0.3, 0.5, 0.7]:
            pr = (AN.db_qps > K * base) & (AN.resp_avg_ms > tl) & (AN.miss_rate > tm)
            r = cm(pr.values, truth); r.update(K=K, tl=tl, tm=tm); grid.append(r)
G = pd.DataFrame(grid); G.to_csv(SP + "/rule_grid.csv", index=False)
S["rule_grid_default"] = G[(G.K == 5) & (G.tl == 200) & (G.tm == 0.5)].iloc[0].to_dict()
S["rule_grid_best_f1"] = G.sort_values("f1", ascending=False).iloc[0].to_dict()
single = {}
for name, pr in {"db only": AN.db_qps > 5 * base, "latency only": AN.resp_avg_ms > 200, "miss only": AN.miss_rate > 0.5,
                 "failures only (>0)": AN.failed > 0,
                 "db+miss": (AN.db_qps > 5 * base) & (AN.miss_rate > 0.5),
                 "all three": (AN.db_qps > 5 * base) & (AN.resp_avg_ms > 200) & (AN.miss_rate > 0.5),
                 "volume (rps>100)": AN.rps > 100}.items():
    single[name] = cm(pr.values, truth)
S["single"] = single
AB = ALL[ALL.valid & (ALL["mode"] == "protected") & ALL.file.isin(["20261022_133456", "20261022_133726", "20261022_134008", "20261022_134303", "20261022_164233", "20261022_165236"])]
S["absorbed"] = {"n": int(len(AB)), "rps_med": float(AB.rps.median()), "db_med": float(AB.db_qps.median()), "resp_med": float(AB.resp_avg_ms.median()),
    "fire": {"volume (rps>100)": round(float((AB.rps > 100).mean()), 3), "db only": round(float((AB.db_qps > 5 * base).mean()), 3),
             "latency only": round(float((AB.resp_avg_ms > 200).mean()), 3), "miss only": round(float((AB.miss_rate > 0.5).mean()), 3),
             "failures only (>0)": round(float((AB.failed > 0).mean()), 3),
             "db+miss": round(float(((AB.db_qps > 5 * base) & (AB.miss_rate > 0.5)).mean()), 3),
             "all three": round(float(((AB.db_qps > 5 * base) & (AB.resp_avg_ms > 200) & (AB.miss_rate > 0.5)).mean()), 3)}}

# offline IsolationForest replay
FEAT = ["db_qps", "resp_avg_ms", "miss_rate", "rps", "fail_s"]
Nn = N.sort_values("ts"); cut = int(len(Nn) * 0.5)
train = Nn.iloc[:cut]; test = pd.concat([Nn.iloc[cut:], A])
y = (test["mode"] == "attack").values
sc = StandardScaler().fit(train[FEAT])
ifr = {}
for cont in [0.01, 0.03, 0.05, 0.10]:
    m = IsolationForest(contamination=cont, random_state=0).fit(sc.transform(train[FEAT]))
    p = m.predict(sc.transform(test[FEAT])) == -1
    r = cm(p, y); s = -m.decision_function(sc.transform(test[FEAT])); r["auc"] = round(roc_auc_score(y, s), 4); ifr[str(cont)] = r
S["if_offline"] = {"train_n": int(len(train)), "test_normal": int((~y).sum()), "test_attack": int(y.sum()), "by_contamination": ifr}
m = IsolationForest(contamination=0.01, random_state=0).fit(sc.transform(train[FEAT]))
s_if = -m.decision_function(sc.transform(test[FEAT]))
rocs = {"IsolationForest (5 features)": s_if}
for f_ in FEAT: rocs[f_] = test[f_].values
S["auc_single"] = {k: round(roc_auc_score(y, v), 4) for k, v in rocs.items()}
ts_eff = {}
for ntr in [10, 20, 50, 100, 200, len(train)]:
    tr = train.iloc[:ntr]; sc2 = StandardScaler().fit(tr[FEAT])
    m2 = IsolationForest(contamination=0.01, random_state=0).fit(sc2.transform(tr[FEAT]))
    p = m2.predict(sc2.transform(test[FEAT])) == -1; ts_eff[int(ntr)] = cm(p, y)
S["if_trainsize"] = ts_eff
S["zsep"] = {f_: round(float((A[f_].median() - train[f_].mean()) / max(train[f_].std(), 1e-9)), 1) for f_ in FEAT}
Pi = F[F["mode"] == "protected"]; Id = F[F["mode"] == "idle"]
S["if_offline_other"] = {"protected_flag": round(float((m.predict(sc.transform(Pi[FEAT])) == -1).mean()), 3),
                         "idle_flag": round(float((m.predict(sc.transform(Id[FEAT])) == -1).mean()), 3)}
# seed stability
seeds = []
for sd in range(10):
    ms_ = IsolationForest(contamination=0.01, random_state=sd).fit(sc.transform(train[FEAT]))
    seeds.append(roc_auc_score(y, -ms_.decision_function(sc.transform(test[FEAT]))))
S["if_seed_auc"] = [round(min(seeds), 4), round(max(seeds), 4)]

nm = ALL[ALL.valid & (ALL["mode"] == "normal") & (ALL.dt < 0.7)]
lam = nm.rps.median()
S["baseline_model"] = {"rps_med": float(lam), "db_med": float(nm.db_qps.median()), "n": int(len(nm)),
    "pred": round(100 / (4 + 100 / lam), 2), "miss_med": round(float(nm.miss_rate.median()), 3),
    "pred_miss": round((100 / (4 + 100 / lam)) / lam, 3)}

# ================= FIGURES =================
def shade(ax, g):
    for ep, h in g.groupby("ep"):
        mo = h["mode"].iloc[0]
        ax.axvspan(h.t.iloc[0], h.t.iloc[-1] + 0.5, color=C.get(mo, "#ccc"), alpha=0.12, lw=0)


W = ALL[ALL.file == FINAL]
epids = sorted(W.ep.unique())
seq = [(e, W[W.ep == e]["mode"].iloc[0], len(W[W.ep == e])) for e in epids]
seq = [s for s in seq if s[1] != "idle" and s[2] >= 3]
win = None
for i in range(len(seq) - 3):
    if [s[1] for s in seq[i:i + 4]] == ["normal", "attack", "normal", "protected"] and seq[i + 1][2] > 15 and seq[i + 3][2] > 15 \
            and W[W.ep == seq[i + 1][0]].ml_alert.mean() > 0.5 and W[W.ep == seq[i + 1][0]].rule_alert.mean() > 0.1:
        win = [s[0] for s in seq[i:i + 4]]; break
print("window", win)
T = W[(W.ep >= win[0]) & (W.ep <= win[-1])].copy(); T["t"] = T.ts - T.ts.iloc[0]
win = sorted(T.ep.unique())
fig, axs = plt.subplots(4, 1, figsize=(3.5, 4.9), sharex=True)
for ax, (col, lab) in zip(axs, [("rps", "Requests/s\nat backend"), ("db_qps", "DB query\nattempts/s"), ("resp_avg_ms", "Mean\nlatency (ms)"), ("fail_s", "HTTP 503\nfailures/s")]):
    shade(ax, T); ax.plot(T.t, T[col], color=INK, lw=1.2); ax.set_ylabel(lab, fontsize=8)
ra = T[T.rule_alert == 1]; ma = T[T.ml_alert == 1]
top = T.db_qps.max()
axs[1].plot(ra.t, [top * 1.10] * len(ra), "v", ms=4, color=C["attack"], label="Rule alert")
axs[1].plot(ma.t, [top * 1.22] * len(ma), "s", ms=3, color=C["x"], label="ML alert")
axs[1].set_ylim(0, top * 1.35)
axs[1].legend(loc="upper left", fontsize=7, ncol=1, bbox_to_anchor=(0.0, 0.92))
y0 = T.rps.max() * 1.15; axs[0].set_ylim(0, y0 * 1.05)
for ep in win:
    h = T[T.ep == ep]
    if h["mode"].iloc[0] == "idle" or len(h) < 5: continue
    axs[0].text(h.t.mean(), y0 * 0.93, {"normal": "normal", "attack": "attack", "protected": "defended"}[h["mode"].iloc[0]], ha="center", fontsize=6.5, color=MUTED)
axs[-1].set_xlabel("Time since window start (s)")
fig.align_ylabels(axs); fig.savefig(OUT + "/fig_timeline.pdf"); plt.close()
S["timeline_window"] = {"eps": [int(x) for x in win], "dur": round(float(T.t.max()), 1)}

ms = ["normal", "attack", "protected"]
fig, axs = plt.subplots(2, 2, figsize=(3.5, 3.5))
for ax, (col, lab) in zip(axs.flat, [("db_qps", "DB attempts/s"), ("resp_avg_ms", "Mean latency (ms)"), ("fail_s", "503 failures/s"), ("miss_rate", "Cache-miss rate")]):
    data = [F[F["mode"] == m][col].dropna().values for m in ms]
    bp = ax.boxplot(data, widths=0.55, patch_artist=True, showfliers=False, medianprops=dict(color=INK, lw=1.2))
    for b, m in zip(bp["boxes"], ms): b.set_facecolor(C[m]); b.set_alpha(0.75); b.set_edgecolor(C[m])
    ax.set_xticks([1, 2, 3], ["Normal", "Attack", "Defended"], fontsize=6.3); ax.set_title(lab, fontsize=8, loc="left")
fig.tight_layout(); fig.savefig(OUT + "/fig_boxplots.pdf"); plt.close()

fig, ax = plt.subplots(figsize=(4.4, 2.6))
for m in ms:
    x = np.sort(F[F["mode"] == m].resp_avg_ms.clip(lower=1).values); ax.plot(x, np.arange(1, len(x) + 1) / len(x), color=C[m], label=LBL[m])
ax.set_xscale("log"); ax.set_xlabel("Per-interval mean latency (ms, log scale)"); ax.set_ylabel("Empirical CDF")
ax.legend(fontsize=7, loc="lower right"); fig.savefig(OUT + "/fig_latency_cdf.pdf"); plt.close()

fig, ax = plt.subplots(figsize=(3.5, 1.9))
for i, (c, col) in enumerate([("rule_t", C["attack"]), ("ml_t", C["x"])]):
    v = ea[c].dropna().values; jit = np.linspace(-0.12, 0.12, len(v)) if len(v) > 1 else np.zeros(len(v))
    ax.plot(v, i + jit, "o", ms=6, color=col, alpha=0.85, mec="#fcfcfb", mew=1)
    ax.plot([np.median(v)] * 2, [i - 0.3, i + 0.3], color=INK, lw=1.5)
    ax.text(np.median(v), i + 0.38, "median %.1f s (n=%d)" % (np.median(v), len(v)), fontsize=7, ha="center", color=MUTED)
ax.set_yticks([0, 1], ["Rule-based", "IsolationForest"]); ax.set_xlabel("Time from attack onset to first alert (s)"); ax.set_ylim(-0.6, 1.75)
fig.savefig(OUT + "/fig_detect_latency.pdf"); plt.close()

fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.2))
sub = G[G.tm == 0.5]; Ks = sorted(sub.K.unique()); TLs = sorted(sub.tl.unique())
cmap = LinearSegmentedColormap.from_list("b", ["#f4f8fd", "#9ec5f4", "#2a78d6", "#104281"])
for ax, metric, ttl in [(axs[0], "recall", "Recall on attack intervals"), (axs[1], "fpr", "False-positive rate on normal intervals")]:
    M = np.array([[sub[(sub.K == k) & (sub.tl == t)][metric].iloc[0] for t in TLs] for k in Ks])
    vmax = 1 if metric == "recall" else max(0.05, M.max())
    ax.imshow(M, cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
    for i in range(len(Ks)):
        for j in range(len(TLs)):
            ax.text(j, i, ("%.2f" if metric == "recall" else "%.3f") % M[i, j], ha="center", va="center", fontsize=7, color="#ffffff" if M[i, j] > 0.55 * vmax else INK)
    ax.set_xticks(range(len(TLs)), [str(t) for t in TLs]); ax.set_yticks(range(len(Ks)), [str(k) for k in Ks])
    ax.set_xlabel(r"Latency threshold $\tau_L$ (ms)"); ax.set_ylabel(r"DB multiplier $K$"); ax.set_title(ttl, fontsize=8, loc="left"); ax.grid(False)
fig.tight_layout(); fig.savefig(OUT + "/fig_rule_grid.pdf"); plt.close()

fig, ax = plt.subplots(figsize=(3.5, 3.2))
cols = [INK, C["normal"], C["attack"], C["protected"], C["x"], "#6250d6"]
names = {"db_qps": "DB attempts/s only", "resp_avg_ms": "Mean latency only", "miss_rate": "Miss rate only", "rps": "Request rate only", "fail_s": "503 rate only"}
for (k, v), c in zip(rocs.items(), cols):
    fpr, tpr, _ = roc_curve(y, v)
    ax.plot(fpr, tpr, color=c, lw=2.0 if k.startswith("Iso") else 1.1, label="%s (AUC %.3f)" % (names.get(k, k), roc_auc_score(y, v)))
ax.plot([0, 1], [0, 1], ls=":", color=MUTED, lw=0.8); ax.set_xlabel("False-positive rate"); ax.set_ylabel("True-positive rate")
ax.legend(fontsize=6.2, loc="lower right"); fig.savefig(OUT + "/fig_roc.pdf"); plt.close()

dev = []
for f_, g in ALL[ALL.valid].groupby("file"):
    a = g[g["mode"] == "attack"]; p = g[g["mode"] == "protected"]
    if len(p) < 5: continue
    dev.append(dict(file=f_, label=f_[9:11] + ":" + f_[11:13], p_resp=p.resp_avg_ms.median(), a_resp=a.resp_avg_ms.median() if len(a) else np.nan,
                    p_rps=p.rps.median(), p_db=p.db_qps.median(), a_db=a.db_qps.median() if len(a) else np.nan, p_fail=p.fail_s.mean()))
D = pd.DataFrame(dev); S["dev"] = D.round(2).to_dict("records")
fig, axs = plt.subplots(2, 1, figsize=(3.5, 3.4), sharex=True)
x = np.arange(len(D))
axs[0].plot(x, D.a_resp, "o-", color=C["attack"], label="Undefended attack"); axs[0].plot(x, D.p_resp, "o-", color=C["protected"], label="Defended attack")
axs[0].set_ylabel("Median latency (ms)", fontsize=8); axs[0].legend(fontsize=7, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0))
axs[1].bar(x, D.p_rps, color=C["normal"], width=0.55); axs[1].set_ylabel("Backend req/s\n(defended, median)", fontsize=8)
axs[1].set_xticks(x, D.label, fontsize=6, rotation=55); axs[1].set_xlabel("Session start time (22 Oct 2026)")
fig.align_ylabels(axs); fig.savefig(OUT + "/fig_dev_evolution.pdf"); plt.close()

fig, ax = plt.subplots(figsize=(3.5, 2.6))
for mo in ms:
    g = F[F["mode"] == mo]; ax.scatter(g.db_qps, g.fail_s, s=7, alpha=0.35, color=C[mo], label=LBL[mo], lw=0)
ax.axvline(12 / 0.11, ls="--", color=MUTED, lw=0.8)
ax.text(12 / 0.11 + 4, ax.get_ylim()[1] * 0.88, "nominal pool capacity\n" + r"$c/d \approx 109$ q/s", fontsize=7, color=MUTED)
ax.set_xlabel("DB query attempts/s"); ax.set_ylabel("HTTP 503 failures/s"); ax.legend(fontsize=7, loc="upper left", markerscale=2)
fig.savefig(OUT + "/fig_db_saturation.pdf"); plt.close()

fig, ax = plt.subplots(figsize=(4.0, 2.7))
ax.scatter(nm.rps, nm.db_qps, s=5, alpha=0.25, color=C["normal"], lw=0, label="Observed normal intervals")
xr = np.linspace(5, 45, 100); ax.plot(xr, 100 / (4 + 100 / xr), color=INK, lw=1.4, label=r"Model $K/(T+K/\lambda)$")
ax.set_xlabel(r"Request rate $\lambda$ (req/s)"); ax.set_ylabel("DB queries/s"); ax.legend(fontsize=7, loc="upper left")
ax.set_xlim(5, 45); ax.set_ylim(0, 40); fig.savefig(OUT + "/fig_baseline_model.pdf"); plt.close()

json.dump(S, open(SP + "/stats.json", "w"), indent=1, default=str)
print(json.dumps(S, indent=1, default=str))
print(E.to_string()); print(D.round(1).to_string())
