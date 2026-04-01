"""Session orchestration for vibebencher."""

import random
import string

from rich.progress import Progress, SpinnerColumn, TextColumn

from vibebencher import ollama, db, ranking
from vibebencher.display import console, show_blinded_responses, show_reveal_table


def select_models_ollama(available_models):
    """Interactive model selection for Ollama. Returns list of selected model names."""
    import questionary
    from questionary import Choice

    if len(available_models) < 2:
        console.print("[red]Need at least 2 models available in Ollama.[/red]")
        raise SystemExit(1)

    defaults = db.get_default_models("ollama")
    choices = [Choice(m, checked=m in defaults) for m in available_models]

    selected = questionary.checkbox(
        "Select models to compare (space to select, enter to confirm):",
        choices=choices,
    ).ask()

    if not selected or len(selected) < 2:
        console.print("[red]Select at least 2 models.[/red]")
        raise SystemExit(1)

    return selected


def select_models_openrouter():
    """Interactive search-based model selection for OpenRouter. Returns list of model IDs."""
    import questionary
    from questionary import Choice
    from vibebencher import openrouter

    # Pre-fetch model list
    try:
        openrouter.list_models()
    except ConnectionError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    defaults = db.get_default_models("openrouter")
    selected = list(defaults)

    while True:
        if selected:
            console.print(f"[cyan]Selected so far: {', '.join(selected)}[/cyan]")

        query = questionary.text(
            "Search OpenRouter models (or 'done' to finish):"
        ).ask()

        if not query:
            continue

        if query.strip().lower() == "done":
            if len(selected) < 2:
                console.print("[red]Select at least 2 models.[/red]")
                continue
            return selected

        matches = openrouter.search_models(query.strip())
        if not matches:
            console.print("[yellow]No models found. Try a different query.[/yellow]")
            continue

        # Cap results at 20
        matches = matches[:20]
        choices = [
            Choice(
                f"{m['id']} ({m['name']})", value=m["id"], checked=m["id"] in selected
            )
            for m in matches
        ]

        picked = questionary.checkbox(
            f"Found {len(matches)} models — select to add (space to select, enter to confirm):",
            choices=choices,
        ).ask()

        if picked is None:
            continue

        # Merge picks: add newly checked, remove newly unchecked from this batch
        match_ids = {m["id"] for m in matches}
        # Remove any from this batch that were unchecked
        selected = [s for s in selected if s not in match_ids or s in picked]
        # Add any newly picked
        for p in picked:
            if p not in selected:
                selected.append(p)


def get_prompt():
    """Get the benchmark prompt from the user."""
    import questionary

    prompt = questionary.text("Enter your prompt:").ask()
    if not prompt or not prompt.strip():
        console.print("[red]Prompt cannot be empty.[/red]")
        raise SystemExit(1)
    return prompt.strip()


def query_models(models, prompt, generate_fn, on_model_done=None):
    """Query each model and return list of {model, response, duration_ms, eval_count, prompt_eval_count}."""
    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for model in models:
            model_num = models.index(model) + 1
            task = progress.add_task(f"Querying model #{model_num}...", total=None)
            try:
                result = generate_fn(model, prompt)
                result["model"] = model
                results.append(result)
            except ConnectionError as e:
                console.print(f"[red]Error querying {model}: {e}[/red]")
                continue
            finally:
                progress.remove_task(task)
                if on_model_done:
                    on_model_done(model)

    if len(results) < 2:
        console.print("[red]Need at least 2 successful responses to compare.[/red]")
        raise SystemExit(1)

    return results


def blind_and_display(results):
    """Shuffle results, assign letter labels, display blinded responses.
    Returns list of (letter, result_dict) tuples in display order.
    """
    shuffled = list(results)
    random.shuffle(shuffled)

    letters = list(string.ascii_uppercase[: len(shuffled)])
    labeled = list(zip(letters, shuffled))

    display_data = [(letter, r["response"]) for letter, r in labeled]
    show_blinded_responses(display_data)

    return labeled


def collect_ranking(labeled):
    """Ask user to rank responses best to worst. Returns ordered list of letters."""
    import questionary

    letters = [letter for letter, _ in labeled]
    letters_str = " ".join(letters)

    while True:
        answer = questionary.text(f"Rank best to worst (e.g. {letters_str}):").ask()

        if not answer:
            continue

        ranked = answer.upper().split()

        if sorted(ranked) != sorted(letters):
            console.print(f"[red]Please rank all responses: {letters_str}[/red]")
            continue

        return ranked


def collect_quality(labeled):
    """Ask user to mark each response as good or bad. Returns {letter: 'good'/'bad'}."""
    import questionary

    qualities = {}
    for letter, _ in labeled:
        choice = questionary.select(
            f"Response {letter}:",
            choices=["good", "bad"],
        ).ask()
        qualities[letter] = choice

    return qualities


def _select_model_pool(providers):
    """Build the model pool and generate functions from providers. Returns (all_models, generate_fns)."""
    all_models = []
    generate_fns = {}

    for provider in providers:
        if provider == "ollama":
            try:
                available = ollama.list_models()
            except ConnectionError as e:
                console.print(f"[red]{e}[/red]")
                raise SystemExit(1)

            selected = select_models_ollama(available)
            all_models.extend(selected)
            for m in selected:
                generate_fns[m] = ollama.generate

        elif provider == "openrouter":
            from vibebencher import openrouter

            selected = select_models_openrouter()
            all_models.extend(selected)
            for m in selected:
                generate_fns[m] = openrouter.generate

    if len(all_models) < 2:
        console.print("[red]Select at least 2 models total.[/red]")
        raise SystemExit(1)

    return all_models, generate_fns


def _run_one_round(all_models, generate_fns, db_name=None):
    """Run one or more benchmark rounds: prompt, ask rounds, each round = 2 models."""
    import questionary

    prompt = get_prompt()

    while True:
        answer = questionary.text("How many rounds? [default: 1]").ask()
        if answer is None:
            raise SystemExit(0)
        if not answer.strip():
            n_rounds = 1
            break
        try:
            n_rounds = int(answer.strip())
            if n_rounds < 1:
                console.print("[red]Need at least 1 round.[/red]")
                continue
            break
        except ValueError:
            console.print("[red]Enter a valid number.[/red]")
            continue

    def dispatch_generate(model, prompt):
        return generate_fns[model](model, prompt)

    def unload_after_generate(model):
        if model in generate_fns and generate_fns[model] == ollama.generate:
            try:
                ollama.unload_model(model)
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to unload model {model}: {e}[/yellow]"
                )

    conn = db.get_connection(db_name)
    try:
        session_id = db.save_session(conn, prompt)

        for round_num in range(1, n_rounds + 1):
            if n_rounds > 1:
                console.print(f"\n[bold]── Sub-round {round_num}/{n_rounds} ──[/bold]")

            matchup = random.sample(all_models, 2)
            console.print(
                f"[dim]Matchup: 2 models selected from pool of {len(all_models)}[/dim]"
            )

            results = query_models(
                matchup, prompt, dispatch_generate, on_model_done=unload_after_generate
            )
            labeled = blind_and_display(results)
            ranked_letters = collect_ranking(labeled)
            qualities = collect_quality(labeled)

            letter_to_result = {letter: result for letter, result in labeled}
            reveal_data = []
            ranked_models = []

            for rank_idx, letter in enumerate(ranked_letters, 1):
                result = letter_to_result[letter]
                reveal_data.append(
                    {
                        "letter": letter,
                        "model": result["model"],
                        "rank": rank_idx,
                        "quality": qualities[letter],
                        "duration_ms": result["duration_ms"],
                        "eval_count": result["eval_count"],
                    }
                )
                ranked_models.append(result["model"])

            show_reveal_table(reveal_data)

            response_ids = {}
            for letter, result in labeled:
                rid = db.save_response(
                    conn,
                    session_id,
                    result["model"],
                    result["response"],
                    result["duration_ms"],
                    result["eval_count"],
                    result["prompt_eval_count"],
                    thinking=result.get("thinking"),
                )
                response_ids[letter] = rid

            for rank_idx, letter in enumerate(ranked_letters, 1):
                db.save_judgment(
                    conn, response_ids[letter], session_id, rank_idx, qualities[letter]
                )

            current_ratings = {m: db.get_elo_for_model(conn, m) for m in ranked_models}
            new_ratings = ranking.update_ratings(ranked_models, current_ratings)
            wl_deltas = ranking.compute_win_loss_deltas(ranked_models)

            for model in ranked_models:
                wins, losses = wl_deltas[model]
                db.set_elo(conn, model, new_ratings[model], wins, losses)

            console.print("[green]Round saved and Elo updated.[/green]")

        console.print(f"[green]Session complete: {n_rounds} round(s) saved.[/green]")
    finally:
        conn.close()


def run_session(providers=None, loop=False, db_name=None):
    """Run benchmark session(s).

    providers: list of provider names. Defaults to ["ollama"].
    loop: if True, keep prompting until user quits (Ctrl-C or empty prompt).
    db_name: database name to save results to.
    """
    if providers is None:
        providers = ["ollama"]

    all_models, generate_fns = _select_model_pool(providers)

    if loop:
        console.print(
            f"[cyan]Loop mode — {len(all_models)} models in pool. Ctrl-C to stop.[/cyan]"
        )
        round_num = 0
        while True:
            round_num += 1
            console.print(f"\n[bold]── Round {round_num} ──[/bold]")
            try:
                _run_one_round(all_models, generate_fns, db_name=db_name)
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Loop ended.[/yellow]")
                break
    else:
        _run_one_round(all_models, generate_fns, db_name=db_name)
