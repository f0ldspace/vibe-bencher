"""JSON and CSV export for vibebencher."""

import csv
import json

from vibebencher import db


def get_parameter_group(params):
    """Get parameter group name for grouping."""
    if params is None:
        return "Unknown"
    elif params < 9:
        return "<9B"
    elif params <= 14:
        return "9-14B"
    elif params <= 30:
        return "15-30B"
    elif params <= 70:
        return "31-70B"
    else:
        return ">70B"


def export_json(output_path, db_name=None):
    """Export all sessions as a JSON array of denormalized objects."""
    conn = db.get_connection(db_name)
    try:
        rows = db.get_all_sessions_denormalized(conn)
        data = []
        for row in rows:
            data.append(
                {
                    "session_id": row["session_id"],
                    "created_at": row["created_at"],
                    "prompt": row["prompt"],
                    "notes": row["notes"],
                    "model_name": row["model_name"],
                    "response": row["response"],
                    "duration_ms": row["duration_ms"],
                    "eval_count": row["eval_count"],
                    "prompt_eval_count": row["prompt_eval_count"],
                    "rank": row["rank"],
                    "quality": row["quality"],
                }
            )

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        return len(data)
    finally:
        conn.close()


def export_csv(output_path, db_name=None):
    """Export all sessions as CSV with one row per response."""
    conn = db.get_connection(db_name)
    try:
        rows = db.get_all_sessions_denormalized(conn)

        fieldnames = [
            "session_id",
            "created_at",
            "prompt",
            "notes",
            "model_name",
            "response",
            "duration_ms",
            "eval_count",
            "prompt_eval_count",
            "rank",
            "quality",
        ]

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row[k] for k in fieldnames})

        return len(rows)
    finally:
        conn.close()


def export_markdown(output_path, db_name=None, group_by_params=False):
    """Export model stats as a markdown table (mirrors 'vb stats' output)."""
    conn = db.get_connection(db_name)
    try:
        stats = db.get_model_stats(conn)
        if group_by_params:
            return _write_markdown_grouped(stats, output_path, conn)
        return _write_markdown_table(stats, output_path, conn, "Model Rankings")
    finally:
        conn.close()


def _format_params(params):
    """Format parameter count for display."""
    if params is None:
        return "?"
    if params == int(params):
        return f"{int(params)}B"
    return f"{params:.1f}B"


def _format_row(row, conn):
    """Format a single stats row for markdown table."""
    params = (
        db.resolve_params(conn, row["model_name"])
        if conn
        else db.extract_parameters(row["model_name"])
    )
    return [
        row["model_name"],
        _format_params(params),
        f"{row['elo']:.0f}",
        str(row["sessions_count"]),
        f"{row['win_pct']:.1f}%" if row["win_pct"] is not None else "-",
        f"{row['good_pct']:.1f}%" if row["good_pct"] is not None else "-",
        str(int(row["avg_tokens"])) if row["avg_tokens"] else "-",
    ]


def _write_markdown_table(stats, output_path, conn, title):
    """Write stats as a single markdown table."""
    headers = ["Model", "Params", "Elo", "Sessions", "Win%", "Good%", "Avg Tokens"]
    lines = [f"# {title}", "", "| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] + ["---:"] * (len(headers) - 1)) + " |")
    for row in stats:
        lines.append("| " + " | ".join(_format_row(row, conn)) + " |")
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(stats)


def _write_markdown_grouped(stats, output_path, conn):
    """Export as multiple tables grouped by parameter ranges."""
    groups = {}
    for row in stats:
        params = (
            db.resolve_params(conn, row["model_name"])
            if conn
            else db.extract_parameters(row["model_name"])
        )
        group_name = get_parameter_group(params)
        groups.setdefault(group_name, []).append(row)

    lines = ["# Model Rankings (Grouped by Parameters)", ""]
    group_order = ["<9B", "9-14B", "15-30B", "31-70B", ">70B", "Unknown"]

    for group_name in group_order:
        if group_name not in groups:
            continue
        group_stats = sorted(groups[group_name], key=lambda x: x["elo"], reverse=True)
        headers = ["Model", "Params", "Elo", "Sessions", "Win%", "Good%", "Avg Tokens"]
        lines.append(f"## {group_name}")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] + ["---:"] * (len(headers) - 1)) + " |")
        for row in group_stats:
            lines.append("| " + " | ".join(_format_row(row, conn)) + " |")
        lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(stats)
