K_FACTOR = 32


def calc_multiplayer_elo(data: list) -> dict:
    """data: [{user_id, elo, is_winner}] → {user_id: delta}"""
    changes = {d["user_id"]: 0 for d in data}
    n = len(data)
    if n < 2:
        return changes
    for i in range(n):
        for j in range(i + 1, n):
            a, b = data[i], data[j]
            if a["is_winner"] and not b["is_winner"]:   sa = 1
            elif b["is_winner"] and not a["is_winner"]: sa = 0
            else:                                        sa = 0.5
            ea = 1 / (1 + 10 ** ((b["elo"] - a["elo"]) / 400))
            changes[a["user_id"]] += round(K_FACTOR * (sa - ea))
            changes[b["user_id"]] += round(K_FACTOR * ((1 - sa) - (1 - ea)))
    return changes