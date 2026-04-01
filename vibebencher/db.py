"""SQLite database for vibebencher."""

import json
import os
import re
import sqlite3
from pathlib import Path

DB_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "vibebencher"
)
DATABASES_DIR = DB_DIR / "databases"
CONFIG_PATH = DB_DIR / "config.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    prompt TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    model_name TEXT NOT NULL,
    response TEXT NOT NULL,
    thinking TEXT,
    duration_ms INTEGER,
    eval_count INTEGER,
    prompt_eval_count INTEGER
);

CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id INTEGER NOT NULL REFERENCES responses(id),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    rank INTEGER NOT NULL,
    quality TEXT NOT NULL CHECK(quality IN ('good', 'bad'))
);

CREATE TABLE IF NOT EXISTS elo_scores (
    model_name TEXT PRIMARY KEY,
    score REAL NOT NULL DEFAULT 1000,
    sessions_count INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS model_params (
    model_name TEXT PRIMARY KEY,
    parameter_size TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'ollama',
    cached_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def list_databases():
    """List available database names. Returns list of strings."""
    if not DATABASES_DIR.exists():
        return []
    return sorted(p.stem for p in DATABASES_DIR.glob("*.db"))


def _migrate_legacy_db():
    """Move old vibebencher.db into databases/default.db if it exists."""
    legacy = DB_DIR / "vibebencher.db"
    if legacy.exists() and not (DATABASES_DIR / "default.db").exists():
        DATABASES_DIR.mkdir(parents=True, exist_ok=True)
        legacy.rename(DATABASES_DIR / "default.db")


def select_database():
    """Interactive database selection. Returns database name."""
    import questionary

    _migrate_legacy_db()
    existing = list_databases()

    if not existing:
        name = questionary.text(
            "No databases yet. Enter a name for your first database:", default="default"
        ).ask()
        if not name or not name.strip():
            name = "default"
        return name.strip()

    choices = existing + ["+ Create new database"]
    picked = questionary.select("Select database:", choices=choices).ask()
    if picked is None:
        raise SystemExit(0)

    if picked == "+ Create new database":
        name = questionary.text("Database name:").ask()
        if not name or not name.strip():
            raise SystemExit(1)
        return name.strip()

    return picked


def get_connection(db_name=None):
    """Get a database connection, creating the DB and schema if needed."""
    if db_name is None:
        db_name = "default"
    DATABASES_DIR.mkdir(parents=True, exist_ok=True)
    db_path = DATABASES_DIR / f"{db_name}.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate_add_thinking_column(conn)
    return conn


def _migrate_add_thinking_column(conn):
    """Add 'thinking' column to responses table if it doesn't exist (for pre-existing DBs)."""
    columns = [
        row[1] for row in conn.execute("PRAGMA table_info(responses)").fetchall()
    ]
    if "thinking" not in columns:
        conn.execute("ALTER TABLE responses ADD COLUMN thinking TEXT")
        conn.commit()


def save_session(conn, prompt, notes=None):
    """Insert a session and return its id."""
    cur = conn.execute(
        "INSERT INTO sessions (prompt, notes) VALUES (?, ?)", (prompt, notes)
    )
    conn.commit()
    return cur.lastrowid


def save_response(
    conn,
    session_id,
    model_name,
    response,
    duration_ms,
    eval_count,
    prompt_eval_count,
    thinking=None,
):
    """Insert a response and return its id."""
    cur = conn.execute(
        "INSERT INTO responses (session_id, model_name, response, thinking, duration_ms, eval_count, prompt_eval_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            model_name,
            response,
            thinking or None,
            duration_ms,
            eval_count,
            prompt_eval_count,
        ),
    )
    conn.commit()
    return cur.lastrowid


def save_judgment(conn, response_id, session_id, rank, quality):
    """Insert a judgment."""
    conn.execute(
        "INSERT INTO judgments (response_id, session_id, rank, quality) VALUES (?, ?, ?, ?)",
        (response_id, session_id, rank, quality),
    )
    conn.commit()


def update_elo(conn, model_name, new_score, is_win):
    """Upsert Elo score for a model."""
    conn.execute(
        """INSERT INTO elo_scores (model_name, score, sessions_count, wins, losses, last_updated)
           VALUES (?, ?, 1, ?, ?, datetime('now'))
           ON CONFLICT(model_name) DO UPDATE SET
             score = ?,
             sessions_count = sessions_count + 1,
             wins = wins + ?,
             losses = losses + ?,
             last_updated = datetime('now')""",
        (
            model_name,
            new_score,
            1 if is_win else 0,
            0 if is_win else 1,
            new_score,
            1 if is_win else 0,
            0 if is_win else 1,
        ),
    )
    conn.commit()


def set_elo(conn, model_name, score, wins_delta, losses_delta):
    """Upsert Elo score with explicit win/loss deltas."""
    conn.execute(
        """INSERT INTO elo_scores (model_name, score, sessions_count, wins, losses, last_updated)
           VALUES (?, ?, 1, ?, ?, datetime('now'))
           ON CONFLICT(model_name) DO UPDATE SET
             score = ?,
             sessions_count = sessions_count + 1,
             wins = wins + ?,
             losses = losses + ?,
             last_updated = datetime('now')""",
        (model_name, score, wins_delta, losses_delta, score, wins_delta, losses_delta),
    )
    conn.commit()


def get_elo_scores(conn):
    """Return all Elo scores ordered by score descending."""
    return conn.execute("SELECT * FROM elo_scores ORDER BY score DESC").fetchall()


def get_elo_for_model(conn, model_name):
    """Return current Elo score for a model, or 1000 if not found."""
    row = conn.execute(
        "SELECT score FROM elo_scores WHERE model_name = ?", (model_name,)
    ).fetchone()
    return row["score"] if row else 1000.0


def get_sessions(conn, last_n=None, model_name=None):
    """Return recent sessions, optionally filtered by model."""
    query = """
        SELECT s.id, s.created_at, s.prompt, s.notes,
               GROUP_CONCAT(DISTINCT r.model_name) as models,
               MIN(CASE WHEN j.rank = 1 THEN r.model_name END) as winner
        FROM sessions s
        JOIN responses r ON r.session_id = s.id
        LEFT JOIN judgments j ON j.response_id = r.id AND j.session_id = s.id
    """
    params = []
    if model_name:
        query += " WHERE r.model_name = ?"
        params.append(model_name)
    query += " GROUP BY s.id ORDER BY s.created_at DESC"
    if last_n:
        query += " LIMIT ?"
        params.append(last_n)
    return conn.execute(query, params).fetchall()


def get_session_detail(conn, session_id):
    """Return full session detail with responses and judgments."""
    session = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not session:
        return None
    responses = conn.execute(
        """SELECT r.*, j.rank, j.quality
           FROM responses r
           LEFT JOIN judgments j ON j.response_id = r.id
           WHERE r.session_id = ?
           ORDER BY j.rank""",
        (session_id,),
    ).fetchall()
    return {"session": session, "responses": responses}


def get_all_sessions_denormalized(conn):
    """Return all data denormalized for export."""
    return conn.execute(
        """SELECT s.id as session_id, s.created_at, s.prompt, s.notes,
                  r.model_name, r.response, r.duration_ms, r.eval_count, r.prompt_eval_count,
                  j.rank, j.quality
           FROM sessions s
           JOIN responses r ON r.session_id = s.id
           LEFT JOIN judgments j ON j.response_id = r.id AND j.session_id = s.id
           ORDER BY s.id, j.rank""",
    ).fetchall()


def extract_parameters(model_name):
    """Extract approximate parameter count from model name.

    Returns parameter count in billions as integer, or None if unknown.
    Handles formats like: 7b, 14b, 32b, 8x7b, etc.
    """
    if not model_name:
        return None

    # Convert to lowercase for case-insensitive matching
    name_lower = model_name.lower()

    # Pattern 1: Mixtral-style expert models (e.g., 8x7b, 4x22b)
    # Extract the per-expert size
    expert_match = re.search(r"(\d+)x(\d+)b", name_lower)
    if expert_match:
        return int(expert_match.group(2))  # Return per-expert size

    # Pattern 2: Standard parameter counts (e.g., 7b, 14b, 32b, 70b)
    # Look for number followed by 'b' (billions)
    param_match = re.search(r"(\d+(?:\.\d+)?)b(?!\w)", name_lower)
    if param_match:
        try:
            return int(float(param_match.group(1)))
        except ValueError:
            pass

    return None


def get_cached_params(conn, model_name):
    """Get cached parameter size string for a model. Returns string like '79.7B' or None."""
    row = conn.execute(
        "SELECT parameter_size FROM model_params WHERE model_name = ?", (model_name,)
    ).fetchone()
    return row["parameter_size"] if row else None


def cache_model_params(conn, model_name, parameter_size, source="ollama"):
    """Cache parameter size for a model. parameter_size is a string like '79.7B'."""
    conn.execute(
        """INSERT INTO model_params (model_name, parameter_size, source, cached_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(model_name) DO UPDATE SET
             parameter_size = ?,
             source = ?,
             cached_at = datetime('now')""",
        (model_name, parameter_size, source, parameter_size, source),
    )
    conn.commit()


def _parse_param_size(parameter_size):
    """Parse a parameter size string like '79.7B' or '137M' into billions as float.
    Returns float or None.
    """
    if not parameter_size:
        return None
    s = parameter_size.strip().upper()
    if s.endswith("B"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    elif s.endswith("M"):
        try:
            return float(s[:-1]) / 1000.0
        except ValueError:
            return None
    return None


def resolve_params(conn, model_name):
    """Resolve parameter count for a model using layered strategy:
    1. Check DB cache (survives model deletion)
    2. Try ollama show API
    3. Fall back to filename regex extraction

    Returns parameter count in billions as float, or None if unknown.
    """
    # Layer 1: DB cache
    cached = get_cached_params(conn, model_name)
    if cached:
        return _parse_param_size(cached)

    # Layer 2: Try ollama show API (works for any Ollama model, including hf.co/* names)
    try:
        from vibebencher import ollama

        info = ollama.show_model(model_name)
        if info and info.get("parameter_size"):
            cache_model_params(
                conn, model_name, info["parameter_size"], source="ollama"
            )
            return _parse_param_size(info["parameter_size"])
    except Exception:
        pass

    # Layer 3: Filename regex extraction
    extracted = extract_parameters(model_name)
    return float(extracted) if extracted else None


def get_model_stats(conn):
    """Return aggregate stats per model."""
    return conn.execute(
        """SELECT e.model_name, e.score as elo, e.sessions_count, e.wins, e.losses,
                  ROUND(CASE WHEN (e.wins + e.losses) > 0
                        THEN 100.0 * e.wins / (e.wins + e.losses) ELSE 0 END, 1) as win_pct,
                  ROUND(100.0 * COUNT(CASE WHEN j.quality = 'good' THEN 1 END) /
                        NULLIF(COUNT(j.id), 0), 1) as good_pct,
                  ROUND(AVG(r.eval_count), 0) as avg_tokens
           FROM elo_scores e
           LEFT JOIN responses r ON r.model_name = e.model_name
           LEFT JOIN judgments j ON j.response_id = r.id
           GROUP BY e.model_name
           ORDER BY e.score DESC""",
    ).fetchall()


def get_config(key):
    """Read a value from config.json. Returns None if not found."""
    if not CONFIG_PATH.exists():
        return None
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        return config.get(key)
    except (json.JSONDecodeError, OSError):
        return None


def set_config(key, value):
    """Write a value to config.json."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    config = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    config[key] = value
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_default_models(provider="ollama"):
    """Load default models from config. Returns list of model names or empty list."""
    key = f"default_models_{provider}"
    models = get_config(key)
    if models is not None:
        return models
    # Migrate legacy key for ollama
    if provider == "ollama":
        legacy = get_config("default_models")
        if legacy:
            return legacy
    return []


def save_default_models(provider, models):
    """Save default models to config."""
    set_config(f"default_models_{provider}", models)
