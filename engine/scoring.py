"""Turn match summaries into a leaderboard."""
from collections import defaultdict
from typing import Dict, Iterable, List


def placement_points(place: int, k: int) -> int:
    """k=4: 3, 1, -1, -3."""
    return (k - 1) - 2 * (place - 1)


def leaderboard(summaries: Iterable[dict]) -> List[Dict]:
    stats = defaultdict(lambda: {"matches": 0, "points": 0.0, "wins": 0, "place_sum": 0,
                                 "faults": 0, "dq": 0})
    ratings = {}
    rating_matches = []
    for m in summaries:
        k = len(m["seats"])
        for seat, name in enumerate(m["seats"]):
            place = m["placements"][seat]
            s = stats[name]
            s["matches"] += 1
            s["points"] += placement_points(place, k)
            s["wins"] += place == 1
            s["place_sum"] += place
            s["faults"] += sum(m["faults"][seat].values())
            s["dq"] += bool(m["disqualified"][seat])
        rating_matches.append((m["seats"], m["placements"]))

    try:  # optional: pip install openskill
        from openskill.models import PlackettLuce
        model = PlackettLuce()
        for name in stats:
            ratings[name] = model.rating(name=name)
        for seats, placements in rating_matches:
            teams = [[ratings[n]] for n in seats]
            new = model.rate(teams, ranks=placements)
            for n, team in zip(seats, new):
                ratings[n] = team[0]
    except ImportError:
        model = None

    rows = []
    for name, s in stats.items():
        row = {
            "name": name,
            "matches": s["matches"],
            "avg_points": round(s["points"] / s["matches"], 4),
            "win_rate": round(s["wins"] / s["matches"], 4),
            "avg_place": round(s["place_sum"] / s["matches"], 4),
            "faults": s["faults"],
            "disqualified": s["dq"],
        }
        if name in ratings:
            r = ratings[name]
            row["skill"] = round(r.mu - 3 * r.sigma, 3)
        rows.append(row)
    rows.sort(key=lambda r: (-r["avg_points"], r["avg_place"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows
