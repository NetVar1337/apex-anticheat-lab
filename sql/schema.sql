-- Match-integrity / anti-cheat telemetry schema.
-- Target: any SQL engine with window functions (PostgreSQL, BigQuery, Snowflake, DuckDB).
-- Deliberately engine-neutral: no game-specific types.

CREATE TABLE players (
    player_id        BIGINT PRIMARY KEY,
    account_created  TIMESTAMP NOT NULL,
    account_level    INT,
    region           TEXT,
    platform         TEXT,          -- pc / playstation / xbox / switch
    input_device     TEXT,          -- mouse / controller / emulator
    rank_tier        TEXT,          -- bronze .. predator
    rank_rp          INT,
    is_banned        BOOLEAN DEFAULT FALSE,
    banned_at        TIMESTAMP,
    ban_reason       TEXT           -- aimbot / wallhack / boosting / account_sharing / ...
);

CREATE TABLE hardware (
    hw_id            BIGINT PRIMARY KEY,
    fingerprint      TEXT NOT NULL,      -- canonical hashed machine fingerprint
    first_seen       TIMESTAMP NOT NULL,
    last_seen        TIMESTAMP NOT NULL,
    mb_uuid          TEXT,
    disk_serial      TEXT,
    mac_vendor       TEXT,
    tpm_present      BOOLEAN,
    tpm_quote_ok     BOOLEAN,
    is_spoofed_suspect BOOLEAN DEFAULT FALSE
);

CREATE TABLE player_hw (
    player_id        BIGINT REFERENCES players(player_id),
    hw_id            BIGINT REFERENCES hardware(hw_id),
    first_seen       TIMESTAMP,
    last_seen        TIMESTAMP,
    PRIMARY KEY (player_id, hw_id)
);

CREATE TABLE matches (
    match_id         BIGINT PRIMARY KEY,
    started_at       TIMESTAMP NOT NULL,
    map              TEXT,
    queue            TEXT,          -- ranked / pubs / mixtape
    region           TEXT,
    server_build     TEXT
);

CREATE TABLE match_players (
    match_id         BIGINT REFERENCES matches(match_id),
    player_id        BIGINT REFERENCES players(player_id),
    squad_id         INT,
    placement        INT,
    damage           INT,
    kills            INT,
    assists          INT,
    knocks           INT,
    headshots        INT,
    shots_fired      INT,
    shots_hit        INT,
    survival_ms      INT,
    rp_delta         INT,
    PRIMARY KEY (match_id, player_id)
);

-- Per-input-event stream, partitioned by day in production.
CREATE TABLE input_events (
    match_id         BIGINT,
    player_id        BIGINT,
    t_ms             INT,
    event            TEXT,          -- move / fire / hit / target_enter / target_exit
    yaw              DOUBLE PRECISION,
    pitch            DOUBLE PRECISION,
    mouse_dx         DOUBLE PRECISION,
    mouse_dy         DOUBLE PRECISION,
    weapon_id        TEXT,
    hit_bone         TEXT,
    distance_m       DOUBLE PRECISION
);

CREATE TABLE sessions (
    session_id       BIGINT PRIMARY KEY,
    player_id        BIGINT REFERENCES players(player_id),
    hw_id            BIGINT,
    started_at       TIMESTAMP NOT NULL,
    ended_at         TIMESTAMP,
    ip_asn           TEXT,
    ip_country       TEXT,
    ip_city          TEXT,
    client_build     TEXT
);

CREATE TABLE auth_events (
    event_id         BIGINT PRIMARY KEY,
    player_id        BIGINT,
    ts               TIMESTAMP NOT NULL,
    kind             TEXT,          -- login / logout / token_refresh / password_reset / mfa
    success          BOOLEAN,
    ip_asn           TEXT,
    ip_country       TEXT,
    device_id        TEXT,
    user_agent       TEXT
);

CREATE TABLE enforcement (
    action_id        BIGINT PRIMARY KEY,
    player_id        BIGINT,
    ts               TIMESTAMP NOT NULL,
    action           TEXT,          -- ban / suspend / rp_scrub / warning / hwid_ban
    reason           TEXT,
    wave_id          TEXT,
    appeal_outcome   TEXT           -- upheld / overturned / pending
);
