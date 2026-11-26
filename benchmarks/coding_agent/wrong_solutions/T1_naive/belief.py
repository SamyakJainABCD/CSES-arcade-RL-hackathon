"""Plausible but wrong for this engine: live shells left / shells left (correct only for a shuffled gun)."""


def p_next_live(obs: dict) -> float:
    if obs["next_round"] in ("LIVE", "BLANK"):
        return 1.0 if obs["next_round"] == "LIVE" else 0.0
    ej = obs["ejections"]
    lives = obs["lives_init"] - obs["lives_shot"] - ej["lives_ejected"]
    return lives / obs["rounds_remaining"] if obs["rounds_remaining"] else 0.0
