"""Rich display helpers for vibebencher."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown

console = Console()


def show_blinded_responses(labeled_responses):
    """Display responses in panels labeled by letter only."""
    console.print()
    for letter, text in labeled_responses:
        panel = Panel(
            Markdown(text),
            title=f"[bold cyan]Response {letter}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
        console.print(panel)
        console.print()


def show_reveal_table(reveal_data):
    """Show the reveal table after judging."""
    table = Table(
        title="[bold]Reveal[/bold]", show_header=True, header_style="bold magenta"
    )
    table.add_column("Letter", style="cyan", justify="center")
    table.add_column("Model", style="green")
    table.add_column("Rank", justify="center")
    table.add_column("Quality", justify="center")
    table.add_column("Speed", justify="right")
    table.add_column("Tokens", justify="right")

    for row in sorted(reveal_data, key=lambda r: r["rank"]):
        quality_style = "green" if row["quality"] == "good" else "red"
        duration = f"{row['duration_ms'] / 1000:.1f}s" if row["duration_ms"] else "?"
        tokens = str(row["eval_count"]) if row["eval_count"] else "?"
        table.add_row(
            row["letter"],
            row["model"],
            str(row["rank"]),
            Text(row["quality"], style=quality_style),
            duration,
            tokens,
        )

    console.print()
    console.print(table)
    console.print()


def _make_stats_table(title, rows, default_models, conn):
    """Create and populate a stats table."""
    from vibebencher.db import resolve_params, extract_parameters

    table = Table(
        title=f"[bold]{title}[/bold]",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Model", style="green")
    table.add_column("Params", justify="right", style="cyan")
    table.add_column("Elo", justify="right", style="cyan")
    table.add_column("Sessions", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("Good%", justify="right")
    table.add_column("Avg Tokens", justify="right")

    for row in rows:
        model_name = row["model_name"]
        params = (
            resolve_params(conn, model_name) if conn else extract_parameters(model_name)
        )

        if params is not None:
            params_display = (
                f"{int(params)}B" if params == int(params) else f"{params:.1f}B"
            )
        else:
            params_display = "?"

        model_display = (
            Text(model_name, style="red")
            if model_name not in default_models
            else model_name
        )

        table.add_row(
            model_display,
            params_display,
            f"{row['elo']:.0f}",
            str(row["sessions_count"]),
            f"{row['win_pct']:.1f}%" if row["win_pct"] is not None else "-",
            f"{row['good_pct']:.1f}%" if row["good_pct"] is not None else "-",
            str(int(row["avg_tokens"])) if row["avg_tokens"] else "-",
        )
    return table


def show_stats_table(stats, default_models=None, conn=None):
    """Display Elo stats table."""
    default_models = default_models or set()
    model_rankings = [row for row in stats if row["sessions_count"] >= 20]
    floor_ratings = [row for row in stats if 10 <= row["sessions_count"] < 20]
    provisional = [row for row in stats if row["sessions_count"] < 10]

    if model_rankings:
        console.print()
        console.print(
            _make_stats_table(
                "Model Rankings (20+ sessions)", model_rankings, default_models, conn
            )
        )

    if floor_ratings:
        console.print()
        console.print(
            _make_stats_table(
                "Floor Ratings (10-20 sessions)", floor_ratings, default_models, conn
            )
        )

    if provisional:
        console.print()
        console.print(
            _make_stats_table(
                "Provisional Rankings (<10 sessions)", provisional, default_models, conn
            )
        )

    if model_rankings or floor_ratings or provisional:
        console.print()


def show_history(sessions):
    """Display session history."""
    table = Table(
        title="[bold]Session History[/bold]",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Date", style="cyan")
    table.add_column("Prompt", max_width=50)
    table.add_column("Models")
    table.add_column("Winner", style="green")

    for row in sessions:
        prompt_preview = (
            row["prompt"][:50] + "..." if len(row["prompt"]) > 50 else row["prompt"]
        )
        table.add_row(
            str(row["id"]),
            row["created_at"],
            prompt_preview,
            row["models"] or "-",
            row["winner"] or "-",
        )

    console.print()
    console.print(table)
    console.print()
