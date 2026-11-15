from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import median

GATE_STEP_MINUTES = 1.0
GATE_CAP_MINUTES = 90.0
HEAPING_STEP_CANDIDATES = (60, 30, 15, 10, 5, 1)
DEFAULT_LONG_STAY_THRESHOLD = 45.0
TOLERANCE = 1e-9


def _round_and_cap(step, cap, source):
    if step <= 0 or cap <= 0:
        raise ValueError("设备计时规则无效")
    return {"kind": "round_and_cap", "step": float(step), "cap": float(cap), "source": source}


def _interview_heaping_step(durations):
    for step in HEAPING_STEP_CANDIDATES:
        if all(duration % step == 0 for duration in durations):
            return float(step)
    return 1.0


def measurement_models(snapshot):
    sensor = {}
    for row in snapshot["tables"]["devices"]:
        sensor[row["id"]] = _round_and_cap(row["step"], row["cap"], "devices")
    interview_durations = [row["duration"] for row in snapshot["tables"]["visits"] if row["method"] == "interview"]
    interview = None
    if interview_durations:
        interview = {"kind": "heaped_report", "step": _interview_heaping_step(interview_durations), "source": "visits+paired_timing"}
    return {"sensor": sensor, "gate": _round_and_cap(GATE_STEP_MINUTES, GATE_CAP_MINUTES, "contract"), "interview": interview}


def model_for(models, method, rule):
    if method == "sensor":
        model = models["sensor"].get(rule)
        if model is None:
            raise ValueError("时长或计时规则无效")
        return model
    if method == "gate":
        return models["gate"]
    if method == "interview":
        if models["interview"] is None:
            raise ValueError("回访报整点口径未建立")
        return models["interview"]
    raise ValueError("未知计时方式")


def latent_interval(model, duration):
    if duration < 0:
        raise ValueError("时长或计时规则无效")
    step = model["step"]
    if abs(duration / step - round(duration / step)) > TOLERANCE:
        raise ValueError("记录与计时口径不一致")
    if model["kind"] == "round_and_cap":
        cap = model["cap"]
        if duration > cap + TOLERANCE:
            raise ValueError("记录超过设备封顶")
        if duration >= cap:
            return cap - step / 2.0, math.inf
    return max(0.0, duration - step / 2.0), duration + step / 2.0


def calibration_report(snapshot, models):
    visits = {row["id"]: row for row in snapshot["tables"]["visits"]}
    by_method = defaultdict(list)
    skipped = 0
    for pair in snapshot["tables"]["paired_timing"]:
        probability = pair["inclusion_probability"]
        if not 0 < probability <= 1:
            raise ValueError("校准选择概率无效")
        reference = pair["reference"]
        if not isinstance(reference, (int, float)) or not math.isfinite(reference) or reference < 0:
            raise ValueError("复计参考时长无效")
        visit = visits.get(pair["visit"])
        if visit is None:
            skipped += 1
            continue
        model = model_for(models, visit["method"], visit["rule"])
        lower, upper = latent_interval(model, visit["duration"])
        if not lower - TOLERANCE <= reference <= upper + TOLERANCE:
            raise ValueError("复计资料与记录机制模型不一致")
        by_method[visit["method"]].append((visit["duration"] - reference, 1.0 / probability))
    methods = {}
    for method, rows in sorted(by_method.items()):
        weights = [weight for _, weight in rows]
        total = sum(weights)
        effective = total * total / sum(weight * weight for weight in weights)
        mean_deviation = sum(deviation * weight for deviation, weight in rows) / total
        methods[method] = {
            "pairs": len(rows),
            "effective_sample_size": round(effective, 3),
            "weighted_mean_deviation_minutes": round(mean_deviation, 6),
            "max_abs_deviation_minutes": round(max(abs(deviation) for deviation, _ in rows), 6),
            "interval_coverage": 1.0,
        }
    limited = [
        {"center": row["center"], "reference_coverage": row["reference_coverage"]}
        for row in sorted(snapshot["tables"]["sampling"], key=lambda row: row["center"])
        if row["reference_coverage"] != "all_day"
    ]
    return {
        "weighting": "inverse_inclusion_probability",
        "pairs_used": sum(rows["pairs"] for rows in methods.values()),
        "pairs_skipped_without_visit": skipped,
        "methods": methods,
        "reference_coverage_limits": limited,
        "note": "复计资料按 inclusion_probability 逆概率加权，用于验证机制模型与报整点宽度，不对记录做点式偏误修正",
    }


def _functional_bounds(intervals, threshold):
    lowers = [lower for lower, _ in intervals]
    uppers = [upper for _, upper in intervals]
    count = len(intervals)
    return {
        "median": (median(lowers), median(uppers)),
        "long_stay": (
            sum(1 for lower in lowers if lower >= threshold) / count,
            sum(1 for upper in uppers if upper > threshold) / count,
        ),
    }


def _finite(value):
    return None if math.isinf(value) else value


def _rounded(value):
    return None if value is None else round(value, 6)


def _stratum(dimension, levels, entries, bounds):
    rows = [row for _, _, row in entries]
    return {
        "dimension": dimension,
        "levels": levels,
        "visits": len(rows),
        "groups": len({row["group"] for row in rows}),
        "measurement_basis": {
            "records_by_method": dict(sorted(Counter(row["method"] for row in rows).items())),
            "records_by_rule": dict(sorted(Counter(row["rule"] for row in rows).items())),
            "capped_records": sum(1 for _, upper, _ in entries if math.isinf(upper)),
            "heaped_report_records": sum(1 for row in rows if row["method"] == "interview"),
        },
        "latent_median_minutes": {"lower": _finite(bounds["median"][0]), "upper": _finite(bounds["median"][1])},
        "long_stay_proportion": {"lower": round(bounds["long_stay"][0], 6), "upper": round(bounds["long_stay"][1], 6)},
    }


def _comparison(dimension, a_levels, b_levels, a_bounds, b_bounds, notes):
    rows = []
    for functional, label in (("median", "median_minutes"), ("long_stay", "long_stay_proportion")):
        a_lower, a_upper = a_bounds[functional]
        b_lower, b_upper = b_bounds[functional]
        lower = None if math.isinf(b_upper) else a_lower - b_upper
        upper = None if math.isinf(a_upper) else a_upper - b_lower
        if lower is not None and lower > 0:
            sign = "positive"
        elif upper is not None and upper < 0:
            sign = "negative"
        else:
            sign = "undetermined"
        needed = list(notes)
        if sign == "undetermined":
            needed.append("区间内分布假设：仅凭记录机制无法判定差值符号")
        rows.append({
            "dimension": dimension,
            "a": a_levels,
            "b": b_levels,
            "functional": label,
            "difference_bounds": {"lower": _rounded(lower), "upper": _rounded(upper)},
            "supported_sign": sign,
            "depends_on_extra_assumptions": bool(needed),
            "assumptions_needed": needed,
        })
    return rows


def latent_analysis(snapshot, long_stay_threshold=DEFAULT_LONG_STAY_THRESHOLD):
    if long_stay_threshold <= 0:
        raise ValueError("长停留阈值无效")
    models = measurement_models(snapshot)
    visits = snapshot["tables"]["visits"]
    entries = []
    for row in visits:
        lower, upper = latent_interval(model_for(models, row["method"], row["rule"]), row["duration"])
        entries.append((lower, upper, row))

    bounds_index = {}
    strata = []
    for dimension, field in (("center", "center"), ("guide", "guide")):
        for level in sorted({row[field] for row in visits}):
            subset = [entry for entry in entries if entry[2][field] == level]
            bounds = _functional_bounds([(lower, upper) for lower, upper, _ in subset], long_stay_threshold)
            bounds_index[(dimension, level)] = bounds
            strata.append(_stratum(dimension, {field: level}, subset, bounds))

    calibration = calibration_report(snapshot, models)
    limited_centers = {item["center"] for item in calibration["reference_coverage_limits"]}
    coverage_note = "复计覆盖仅限 daytime 的中心参与其中，计时口径推广到全部时段依赖报数行为稳定的假设"

    guide_by_center = defaultdict(set)
    for row in visits:
        guide_by_center[row["center"]].add(row["guide"])

    comparisons = []
    centers = sorted(guide_by_center)
    for index, first in enumerate(centers):
        for second in centers[index + 1:]:
            if guide_by_center[first] != guide_by_center[second]:
                continue
            notes = []
            if limited_centers.intersection((first, second)):
                notes.append(coverage_note)
            comparisons += _comparison(
                "center", {"center": first}, {"center": second},
                bounds_index[("center", first)], bounds_index[("center", second)], notes,
            )
    guides = sorted({row["guide"] for row in visits})
    if len(guides) > 1:
        notes = []
        if all(len(guide_by_center[center]) == 1 for center in guide_by_center):
            notes.append("讲解方式仅在不同中心之间变化，需要中心之间无其他系统差异的假设")
        if limited_centers:
            notes.append(coverage_note)
        ordered = ["guided", "self"] if {"guided", "self"} == set(guides) else guides
        for index, first in enumerate(ordered):
            for second in ordered[index + 1:]:
                comparisons += _comparison(
                    "guide", {"guide": first}, {"guide": second},
                    bounds_index[("guide", first)], bounds_index[("guide", second)], notes,
                )

    assumptions = [
        "潜在时长仅识别到记录机制决定的区间：sensor 按 devices 规则取整并封顶，gate 取整分钟且 90 分钟封顶，interview 按校准的报整点步长给出区间；区间内部的真实分布未被识别",
        "校准使用 paired_timing 复计资料并按 inclusion_probability 逆概率加权，仅验证机制模型与报整点宽度，不做点式偏误修正",
        "同游团体 group 内记录相关，给出的范围是识别范围而非统计置信区间",
    ]
    if limited_centers:
        assumptions.append("复计仅覆盖 daytime 的中心：%s；将校准口径推广到全部时段是额外假设" % "、".join(sorted(limited_centers)))
    if len(guides) > 1 and all(len(guide_by_center[center]) == 1 for center in guide_by_center):
        assumptions.append("讲解方式仅在不同中心之间变化，guided 与 self 的比较需要中心可比的额外假设")

    model_rows = [
        {"method": "sensor", "rule": rule, "kind": model["kind"], "step_minutes": model["step"], "cap_minutes": model["cap"], "source": model["source"]}
        for rule, model in sorted(models["sensor"].items())
    ]
    model_rows.append({"method": "gate", "kind": "round_and_cap", "step_minutes": GATE_STEP_MINUTES, "cap_minutes": GATE_CAP_MINUTES, "source": "contract"})
    if models["interview"] is not None:
        model_rows.append({
            "method": "interview",
            "kind": "heaped_report",
            "heaping_step_minutes": models["interview"]["step"],
            "half_width_minutes": models["interview"]["step"] / 2.0,
            "source": models["interview"]["source"],
        })

    return {
        "long_stay_threshold_minutes": long_stay_threshold,
        "measurement_models": model_rows,
        "calibration": calibration,
        "strata": strata,
        "comparisons": comparisons,
        "assumptions": assumptions,
        "interpretation": "观测分布在整点附近的尖峰与记录机制一致：interview 全部落在报整点步长上，sensor 按规则取整并在封顶处堆积。潜在时长以与机制相容的范围给出；仅凭现有资料无法完全区分真实峰与报数偏好，比较结论标注了是否依赖额外假设。原始观测分布仍由 observed-overview-v1 提供",
    }
