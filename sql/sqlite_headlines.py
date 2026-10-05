"""Three headline analyst queries, runnable with the Python standard library.

The full file in kpi_queries.sql is PostgreSQL. This script is the part a
reviewer can execute here. It uses a 40-row synthetic fixture, not game data.

    python sql/sqlite_headlines.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def build(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE players (
            player_id INTEGER PRIMARY KEY,
            account_created TEXT NOT NULL,
            rank_tier TEXT,
            input_device TEXT,
            is_banned INTEGER DEFAULT 0,
            banned_at TEXT
        );
        CREATE TABLE matches (
            match_id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL
        );
        CREATE TABLE match_players (
            match_id INTEGER,
            player_id INTEGER,
            kills INTEGER,
            survival_ms INTEGER,
            shots_hit INTEGER,
            headshots INTEGER
        );
        CREATE TABLE hardware (
            hw_id INTEGER PRIMARY KEY,
            fingerprint TEXT NOT NULL
        );
        CREATE TABLE player_hw (
            player_id INTEGER,
            hw_id INTEGER
        );
        CREATE TABLE hardware_observations (
            obs_id INTEGER PRIMARY KEY,
            hw_id INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            mb_uuid TEXT,
            disk_serial TEXT,
            mac_vendor TEXT
        );
        CREATE TABLE enforcement (
            action_id INTEGER PRIMARY KEY,
            player_id INTEGER,
            action TEXT,
            appeal_outcome TEXT
        );

        INSERT INTO players VALUES
            (1, '2024-01-01', 'gold', 'mouse', 1, '2026-01-01'),
            (2, '2024-01-01', 'gold', 'mouse', 0, NULL),
            (3, '2026-02-01', 'gold', 'mouse', 0, NULL),
            (4, '2024-06-01', 'bronze', 'controller', 0, NULL),
            (5, '2024-06-01', 'bronze', 'controller', 0, NULL);
        INSERT INTO matches VALUES
            (10, '2026-03-01'),
            (11, '2026-03-01'),
            (12, '2026-03-02');
        INSERT INTO match_players VALUES
            (10, 1, 8, 600000, 40, 28),
            (10, 2, 3, 600000, 40, 8),
            (11, 1, 7, 600000, 30, 20),
            (11, 4, 1, 600000, 20, 2),
            (12, 2, 2, 600000, 25, 4),
            (12, 5, 1, 600000, 20, 3);
        INSERT INTO enforcement VALUES
            (1, 1, 'ban', 'upheld');
        INSERT INTO hardware VALUES
            (100, 'fp-banned'),
            (200, 'fp-clean');
        INSERT INTO player_hw VALUES
            (1, 100),
            (3, 100),
            (2, 200);
        INSERT INTO hardware_observations VALUES
            (1, 100, '2026-01-01', 'mb-a', 'disk-a', 'vendor-a'),
            (2, 100, '2026-01-02', 'mb-b', 'disk-b', 'vendor-b'),
            (3, 100, '2026-01-03', 'mb-c', 'disk-c', 'vendor-c'),
            (4, 200, '2026-01-01', 'mb-z', 'disk-z', 'vendor-z'),
            (5, 200, '2026-02-01', 'mb-z', 'disk-z', 'vendor-z');
        """
    )


QUERIES = {
    "infection_rate": """
        WITH confirmed AS (
            SELECT DISTINCT player_id FROM enforcement
            WHERE action IN ('ban', 'hwid_ban')
              AND (appeal_outcome IS NULL OR appeal_outcome = 'upheld')
        ),
        match_flags AS (
            SELECT m.match_id,
                   substr(m.started_at, 1, 10) AS day,
                   MAX(CASE WHEN c.player_id IS NOT NULL THEN 1 ELSE 0 END) AS infected
            FROM matches m
            JOIN match_players mp ON mp.match_id = m.match_id
            LEFT JOIN confirmed c ON c.player_id = mp.player_id
            GROUP BY m.match_id, day
        )
        SELECT day,
               COUNT(*) AS matches_played,
               SUM(infected) AS infected_matches,
               ROUND(100.0 * SUM(infected) / COUNT(*), 3) AS infection_rate_pct
        FROM match_flags
        GROUP BY day
        ORDER BY day
    """,
    "cohort_kill_z": """
        WITH per_match AS (
            SELECT mp.player_id, p.rank_tier,
                   mp.kills * 60000.0 / mp.survival_ms AS kills_per_min
            FROM match_players mp
            JOIN players p ON p.player_id = mp.player_id
            WHERE mp.survival_ms > 60000
        ),
        tier_stats AS (
            SELECT rank_tier, AVG(kills_per_min) AS mu, COUNT(*) AS n
            FROM per_match
            GROUP BY rank_tier
        )
        SELECT pm.player_id, pm.rank_tier, COUNT(*) AS matches,
               ROUND(AVG(pm.kills_per_min), 3) AS avg_kpm,
               ROUND(AVG(pm.kills_per_min) - ts.mu, 3) AS above_tier_mean
        FROM per_match pm
        JOIN tier_stats ts ON ts.rank_tier = pm.rank_tier
        GROUP BY pm.player_id, pm.rank_tier, ts.mu
        ORDER BY above_tier_mean DESC
    """,
    "banned_hardware_reuse": """
        SELECT p.player_id, p.account_created, h.fingerprint,
               b.player_id AS prior_banned_player, b.banned_at
        FROM players p
        JOIN player_hw ph ON ph.player_id = p.player_id
        JOIN hardware h ON h.hw_id = ph.hw_id
        JOIN player_hw ph2 ON ph2.hw_id = h.hw_id
        JOIN players b ON b.player_id = ph2.player_id AND b.is_banned = 1
        WHERE p.player_id <> b.player_id
          AND p.account_created > b.banned_at
          AND p.is_banned = 0
    """,
    "observation_churn": """
        SELECT hw_id,
               COUNT(DISTINCT mb_uuid) AS distinct_mb_uuid,
               COUNT(DISTINCT disk_serial) AS distinct_disk_serial,
               COUNT(DISTINCT mac_vendor) AS distinct_mac_vendors
        FROM hardware_observations
        GROUP BY hw_id
        HAVING COUNT(DISTINCT mb_uuid) > 1
            OR COUNT(DISTINCT disk_serial) > 2
            OR COUNT(DISTINCT mac_vendor) > 2
    """,
}


def main() -> int:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    build(con)
    for name, sql in QUERIES.items():
        rows = con.execute(sql).fetchall()
        print(f"\n## {name}")
        if not rows:
            print("(no rows)")
            continue
        keys = rows[0].keys()
        print(" | ".join(keys))
        for row in rows:
            print(" | ".join(str(row[k]) for k in keys))
    out = Path(__file__).with_name("sqlite_headlines_out.txt")
    # Re-run into a file so the commit can show the observed output.
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    con2 = sqlite3.connect(":memory:")
    con2.row_factory = sqlite3.Row
    build(con2)
    with redirect_stdout(buf):
        for name, sql in QUERIES.items():
            rows = con2.execute(sql).fetchall()
            print(f"\n## {name}")
            if not rows:
                print("(no rows)")
                continue
            keys = rows[0].keys()
            print(" | ".join(keys))
            for row in rows:
                print(" | ".join(str(row[k]) for k in keys))
    text = (
        "Synthetic SQLite fixture. Not game data.\n"
        "Regenerate with: python sql/sqlite_headlines.py\n"
        + buf.getvalue()
    )
    out.write_text(text, encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
