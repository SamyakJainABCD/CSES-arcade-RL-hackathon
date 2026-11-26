"""Reference solution for T1 (no unknown ejections): the generator flips a fair coin while both kinds remain."""


def p_next_live(obs: dict) -> float:
    if obs["next_round"] in ("LIVE", "BLANK"):
        return 1.0 if obs["next_round"] == "LIVE" else 0.0
    ej = obs["ejections"]
    lives = obs["lives_init"] - obs["lives_shot"] - ej["lives_ejected"]
    blanks = obs["blanks_init"] - obs["blanks_shot"] - ej["blanks_ejected"]
    if lives > 0 and blanks > 0:
        return 0.5
    return 1.0 if lives > 0 else 0.0
