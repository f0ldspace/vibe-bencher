"""CLI commands for vibebencher."""

import click

from vibebencher.display import console

PROVIDERS = ["ollama", "openrouter"]


@click.group()
def cli():
    """vibebencher - Personal AI benchmarking tool."""
    pass


@cli.command()
@click.option(
    "--provider",
    "providers",
    multiple=True,
    default=["ollama", "openrouter"],
    type=click.Choice(PROVIDERS),
    help="Provider(s) to use (can specify multiple)",
)
@click.option("--loop", is_flag=True, default=False, help="Keep prompting in a loop")
def run(providers, loop):
    """Run a new benchmark session."""
    from vibebencher import db
    from vibebencher.benchmark import run_session

    db_name = db.select_database()
    run_session(providers=list(providers), loop=loop, db_name=db_name)


@cli.command()
@click.option(
    "--provider",
    default="ollama",
    type=click.Choice(PROVIDERS),
    help="Provider to set defaults for",
)
def defaults(provider):
    """Set default models for benchmarking."""
    if provider == "ollama":
        _defaults_ollama()
    elif provider == "openrouter":
        _defaults_openrouter()


def _defaults_ollama():
    from vibebencher import ollama, db
    from questionary import Choice
    import questionary

    try:
        available = ollama.list_models()
    except ConnectionError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    if not available:
        console.print("[red]No models available in Ollama.[/red]")
        raise SystemExit(1)

    current = db.get_default_models("ollama")
    choices = [Choice(m, checked=m in current) for m in available]

    selected = questionary.checkbox(
        "Select default models (space to select, enter to confirm):",
        choices=choices,
    ).ask()

    if selected is None:
        return

    db.save_default_models("ollama", selected)
    if selected:
        console.print(f"[green]Defaults saved: {', '.join(selected)}[/green]")
    else:
        console.print("[yellow]Defaults cleared.[/yellow]")


def _defaults_openrouter():
    from vibebencher import openrouter, db
    from questionary import Choice
    import questionary

    try:
        openrouter.list_models()
    except ConnectionError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    current = db.get_default_models("openrouter")
    selected = list(current)

    while True:
        if selected:
            console.print(f"[cyan]Selected so far: {', '.join(selected)}[/cyan]")

        query = questionary.text(
            "Search OpenRouter models (or 'done' to finish):"
        ).ask()

        if not query:
            continue

        if query.strip().lower() == "done":
            break

        matches = openrouter.search_models(query.strip())
        if not matches:
            console.print("[yellow]No models found. Try a different query.[/yellow]")
            continue

        matches = matches[:20]
        choices = [
            Choice(
                f"{m['id']} ({m['name']})", value=m["id"], checked=m["id"] in selected
            )
            for m in matches
        ]

        picked = questionary.checkbox(
            f"Found {len(matches)} models — select to add:",
            choices=choices,
        ).ask()

        if picked is None:
            continue

        match_ids = {m["id"] for m in matches}
        selected = [s for s in selected if s not in match_ids or s in picked]
        for p in picked:
            if p not in selected:
                selected.append(p)

    db.save_default_models("openrouter", selected)
    if selected:
        console.print(f"[green]Defaults saved: {', '.join(selected)}[/green]")
    else:
        console.print("[yellow]Defaults cleared.[/yellow]")


@cli.command()
@click.argument("key")
@click.argument("value")
def config(key, value):
    """Set a configuration value (e.g. vb config openrouter-key <KEY>)."""
    from vibebencher import db

    key_map = {
        "openrouter-key": "openrouter_api_key",
    }

    config_key = key_map.get(key)
    if not config_key:
        console.print(f"[red]Unknown config key: {key}[/red]")
        console.print(f"[yellow]Available keys: {', '.join(key_map.keys())}[/yellow]")
        raise SystemExit(1)

    db.set_config(config_key, value)
    console.print(f"[green]Saved {key}.[/green]")


@cli.command()
def stats():
    """Show model Elo rankings and stats."""
    from vibebencher import db
    from vibebencher.display import show_stats_table

    db_name = db.select_database()
    conn = db.get_connection(db_name)
    try:
        model_stats = db.get_model_stats(conn)
        if not model_stats:
            console.print("[yellow]No data yet. Run 'vb run' first.[/yellow]")
            return

        # Get all default models from all providers
        default_models = set()
        for provider in PROVIDERS:
            defaults = db.get_default_models(provider)
            default_models.update(defaults)

        show_stats_table(model_stats, default_models, conn=conn)
    finally:
        conn.close()


@cli.command()
@click.option("--last", "last_n", type=int, default=None, help="Show last N sessions")
@click.option("--model", "model_name", default=None, help="Filter by model name")
def history(last_n, model_name):
    """Show session history."""
    from vibebencher import db
    from vibebencher.display import show_history

    db_name = db.select_database()
    conn = db.get_connection(db_name)
    try:
        sessions = db.get_sessions(conn, last_n=last_n, model_name=model_name)
        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return
        show_history(sessions)
    finally:
        conn.close()


@cli.command()
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "csv", "md", "svg"]),
    required=True,
    help="Export format",
)
@click.option("--output", "output_path", required=True, help="Output file path")
@click.option(
    "--group-by-params",
    is_flag=True,
    help="Group models by parameter size (md format only)",
)
def export(fmt, output_path, group_by_params):
    """Export session data."""
    from vibebencher import db
    from vibebencher.export import export_csv, export_json, export_markdown, export_svg

    db_name = db.select_database()
    if fmt == "json":
        count = export_json(output_path, db_name=db_name)
    elif fmt == "csv":
        count = export_csv(output_path, db_name=db_name)
    elif fmt == "svg":
        count = export_svg(output_path, db_name=db_name)
    else:
        count = export_markdown(
            output_path, db_name=db_name, group_by_params=group_by_params
        )

    console.print(f"[green]Exported {count} records to {output_path}[/green]")


@cli.command("refresh-params")
def refresh_params():
    """Fetch and cache parameter counts from Ollama for all known models."""
    from vibebencher import db, ollama

    db_name = db.select_database()
    conn = db.get_connection(db_name)
    try:
        # Get all model names from elo_scores
        rows = conn.execute("SELECT model_name FROM elo_scores").fetchall()
        if not rows:
            console.print("[yellow]No models found. Run 'vb run' first.[/yellow]")
            return

        updated = 0
        skipped = 0
        failed = 0

        for row in rows:
            model_name = row["model_name"]

            info = ollama.show_model(model_name)
            if info and info.get("parameter_size"):
                db.cache_model_params(
                    conn, model_name, info["parameter_size"], source="ollama"
                )
                console.print(
                    f"  [green]{model_name}[/green]: {info['parameter_size']}"
                )
                updated += 1
            else:
                console.print(f"  [yellow]{model_name}[/yellow]: not found in Ollama")
                skipped += 1

        console.print(
            f"\n[green]Updated {updated}[/green], [yellow]skipped {skipped}[/yellow]"
        )
    finally:
        conn.close()
