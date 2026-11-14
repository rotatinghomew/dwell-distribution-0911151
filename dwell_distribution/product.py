from collections import Counter, defaultdict


def raw_histograms(snapshot):
    groups = defaultdict(Counter)
    rules = {row["id"] for row in snapshot["tables"]["devices"]}
    for row in snapshot["tables"]["visits"]:
        if row["duration"] < 0 or row["rule"] not in rules:
            raise ValueError("时长或计时规则无效")
        groups[(row["center"], row["method"])][row["duration"]] += 1
    return [{"center": key[0], "method": key[1], "bins": [{"duration": value, "count": count} for value, count in sorted(counts.items())]} for key, counts in sorted(groups.items())]


def paired_overview(snapshot):
    visits = {row["id"]: row for row in snapshot["tables"]["visits"]}
    result = defaultdict(list)
    for pair in snapshot["tables"]["paired_timing"]:
        if not 0 < pair["inclusion_probability"] <= 1:
            raise ValueError("校准选择概率无效")
        if pair["visit"] in visits:
            visit = visits[pair["visit"]]
            result[visit["method"]].append(visit["duration"] - pair["reference"])
    return {method: {"pairs": len(differences), "observed_mean_difference": sum(differences)/len(differences)} for method, differences in result.items()}


def summarize(snapshot):
    return {"histograms": raw_histograms(snapshot), "paired_observations": paired_overview(snapshot), "interpretation": "仅描述实际记录及配对资料，不代表校正后的潜在时长"}
