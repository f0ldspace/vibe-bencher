"""Elo rating calculation from pairwise comparisons."""

K = 32


def expected_score(rating_a, rating_b):
    """Expected score of player A against player B."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_ratings(rankings, current_ratings):
    """Given a ranking (list of model names, best first) and their current ratings,
    return a dict of {model_name: new_rating} after all pairwise comparisons.

    Every pair (winner, loser) from the ranking order generates one update.
    """
    new_ratings = dict(current_ratings)

    for i in range(len(rankings)):
        for j in range(i + 1, len(rankings)):
            winner = rankings[i]
            loser = rankings[j]

            exp_w = expected_score(new_ratings[winner], new_ratings[loser])
            exp_l = expected_score(new_ratings[loser], new_ratings[winner])

            new_ratings[winner] += K * (1.0 - exp_w)
            new_ratings[loser] += K * (0.0 - exp_l)

    return new_ratings


def compute_win_loss_deltas(rankings):
    """Given a ranking, return {model: (wins, losses)} counts from pairwise comparisons."""
    deltas = {m: [0, 0] for m in rankings}
    for i in range(len(rankings)):
        for j in range(i + 1, len(rankings)):
            deltas[rankings[i]][0] += 1  # win
            deltas[rankings[j]][1] += 1  # loss
    return {m: (w, l) for m, (w, l) in deltas.items()}
