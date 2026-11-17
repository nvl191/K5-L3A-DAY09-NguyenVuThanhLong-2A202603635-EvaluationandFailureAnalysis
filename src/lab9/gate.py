"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    def finite_metrics(report: dict, label: str) -> None:
        metrics = report.get("metrics")
        if not isinstance(metrics, dict):
            problems.append(f"{label}: metrics missing or malformed")
            return
        for name, value in metrics.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(float(value)):
                    problems.append(f"{label}: metric {name} is not finite")

    def report_rows(report: dict, label: str) -> tuple[list[dict], set[tuple[str, int]]]:
        manifest = report.get("manifest") or {}
        rows = report.get("rows")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            problems.append(f"{label}: rows missing or malformed")
            return [], set()
        try:
            items_n = manifest["items"]
            seeds = manifest["seeds"]
            if (not isinstance(items_n, int) or isinstance(items_n, bool) or items_n < 1
                    or not isinstance(seeds, list) or not seeds
                    or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)
                    or len(set(seeds)) != len(seeds)):
                raise ValueError
            expected_n = items_n * len(seeds)
            if len(rows) != expected_n:
                problems.append(f"{label}: row count {len(rows)} != manifest items × seeds {expected_n}")
        except (KeyError, TypeError, ValueError):
            problems.append(f"{label}: manifest items/seeds missing or malformed")

        pairs: list[tuple[str, int]] = []
        for row in rows:
            item_id, seed = row.get("item_id"), row.get("seed")
            if (not isinstance(item_id, str) or not item_id
                    or not isinstance(seed, int) or isinstance(seed, bool)):
                problems.append(f"{label}: row missing valid item_id/seed")
            else:
                pairs.append((item_id, seed))
            for key, value in row.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if not math.isfinite(float(value)):
                        problems.append(f"{label}: row {item_id!r} metric/value {key} is not finite")
                        break
        unique_pairs = set(pairs)
        if len(unique_pairs) != len(pairs):
            problems.append(f"{label}: duplicate (item_id, seed) row(s)")
        if isinstance(manifest.get("items"), int) and len({item for item, _ in unique_pairs}) != manifest["items"]:
            problems.append(f"{label}: unique item count does not match manifest")
        return rows, unique_pairs

    finite_metrics(pr, "PR")
    finite_metrics(base, "baseline")
    expected_metric_ids = {m.get("id") for m in spec.get("metrics", []) if m.get("id")}
    for label, report in (("PR", pr), ("baseline", base)):
        reported = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        missing_metrics = sorted(expected_metric_ids - set(reported))
        if missing_metrics:
            problems.append(f"{label}: missing aggregate metric(s) {', '.join(missing_metrics)}")
    pr_rows, pr_pairs = report_rows(pr, "PR")
    base_rows, base_pairs = report_rows(base, "baseline")
    if pr_pairs != base_pairs:
        missing = len(base_pairs - pr_pairs)
        extra = len(pr_pairs - base_pairs)
        problems.append(f"PR: (item_id, seed) set differs from baseline ({missing} missing, {extra} extra)")

    for label, report in (("PR", pr), ("baseline", base)):
        failures = report.get("evaluator_failures")
        if failures:
            count = len(failures) if isinstance(failures, (list, tuple, set, dict, str)) else 1
            problems.append(f"{label}: evaluator_failures has {count} entry/entries")

    # Evaluator-backed metric values must be present on every row. Aggregate-only
    # metrics such as pass_hat_5 do not live in rows and are checked in metrics above.
    try:
        from lab9.graders import GRADERS
        row_metric_ids = {m["id"] for m in spec.get("metrics", []) if m.get("id") in GRADERS}
    except (ImportError, KeyError, TypeError):
        row_metric_ids = {m["id"] for m in spec.get("metrics", []) if m.get("level") != "system"}
    for label, rows in (("PR", pr_rows), ("baseline", base_rows)):
        for index, row in enumerate(rows):
            for metric_id in row_metric_ids:
                if metric_id not in row or row[metric_id] is None:
                    problems.append(f"{label}: row {index} has missing {metric_id}")
                    break

    # Slice membership is part of the evaluated population. Relabeling an item
    # can hide it from a blocking slice while leaving its score unchanged.
    def slice_membership(rows: list[dict]) -> dict[tuple[str, int], tuple[str, ...]]:
        result = {}
        for row in rows:
            try:
                pair = (str(row["item_id"]), int(row["seed"]))
            except (KeyError, TypeError, ValueError):
                continue
            tags = row.get("slices") or []
            if not isinstance(tags, list):
                problems.append(f"report: row {pair} has malformed slices")
                tags = []
            result[pair] = tuple(sorted(str(tag) for tag in tags))
        return result

    pr_slices, base_slices = slice_membership(pr_rows), slice_membership(base_rows)
    for pair in sorted(pr_pairs & base_pairs):
        if pr_slices.get(pair) != base_slices.get(pair):
            problems.append(f"PR: slice tags differ from baseline for {pair[0]}@{pair[1]}")
            break

    # Ratchet applies only while comparing the same eval-set version.
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        current_metrics = {m.get("id"): m for m in spec.get("metrics", []) if m.get("id")}
        for old in base_spec.get("metrics", []):
            mid = old.get("id")
            new = current_metrics.get(mid)
            if new is None:
                problems.append(f"spec ratchet: metric {mid} was removed")
                continue
            old_th, new_th = old.get("threshold") or {}, new.get("threshold") or {}
            for bound, stricter in (("max", lambda n, o: n <= o), ("min", lambda n, o: n >= o),
                                    ("max_increase", lambda n, o: n <= o)):
                if bound in old_th and (bound not in new_th or not stricter(new_th[bound], old_th[bound])):
                    problems.append(f"spec ratchet: metric {mid} loosened or removed {bound} threshold")
            if old_th.get("no_significant_drop") and not new_th.get("no_significant_drop"):
                problems.append(f"spec ratchet: metric {mid} removed no_significant_drop")
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"spec ratchet: metric {mid} changed from blocking to non-blocking")

        current_slices = {s.get("name"): s for s in spec.get("slices", []) if s.get("name")}
        for old in base_spec.get("slices", []):
            name = old.get("name")
            new = current_slices.get(name)
            if new is None:
                problems.append(f"spec ratchet: slice {name} was removed")
                continue
            if new.get("metric") != old.get("metric"):
                problems.append(f"spec ratchet: slice {name} changed metric")
            old_th = {k: old[k] for k in ("min", "max") if k in old}
            new_th = {k: new[k] for k in ("min", "max") if k in new}
            for bound, stricter in (("max", lambda n, o: n <= o), ("min", lambda n, o: n >= o)):
                if bound in old_th and (bound not in new_th or not stricter(new_th[bound], old_th[bound])):
                    problems.append(f"spec ratchet: slice {name} loosened or removed {bound} threshold")
            if old.get("no_significant_drop") and not new.get("no_significant_drop"):
                problems.append(f"spec ratchet: slice {name} removed no_significant_drop")
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"spec ratchet: slice {name} changed from blocking to non-blocking")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for rule in spec.get("slices", []):
        name, metric = rule["name"], rule["metric"]
        current = per_item(pr, metric, slice_name=name)
        baseline = per_item(base, metric, slice_name=name)
        keys = sorted(set(current) & set(baseline))
        slice_id = f"slice:{name}/{metric}"

        if not current:
            verdict = "MISSING"
            note = "no PR rows in slice"
            value = None
        else:
            value = sum(current.values()) / len(current)
            verdict = "ok"
            note = ""
            if "min" in rule and value < float(rule["min"]):
                verdict = "fail"
                note = f"below min {rule['min']}"
            if rule.get("no_significant_drop"):
                if not keys:
                    verdict = "MISSING"
                    note = "no paired baseline items in slice"
                else:
                    delta, lo, hi = stats.paired_bootstrap(
                        [current[k] for k in keys],
                        [baseline[k] for k in keys],
                        n_resamples=bs.get("n_resamples", 1000),
                        rng=bs.get("rng", 2027),
                        confidence=bs.get("confidence", 0.95),
                    )
                    note = f"Δ {delta:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"

        is_blocking = rule.get("blocking", False)
        if verdict != "ok" and is_blocking:
            blocked.append(slice_id)
        label = "ok" if verdict == "ok" else ("BLOCK" if is_blocking else "warn")
        lines.append(f"  {slice_id:<34} {value!s:<8} {note:<36} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
