-- Match-integrity KPI and triage queries.
-- Engine-neutral SQL (window functions, CTEs). Assumes the schema in schema.sql.
--
-- These are the queries an analyst runs daily: they answer "is the game healthy?",
-- "where should review effort go?", and "did the last enforcement wave work?".

-- ---------------------------------------------------------------------------
-- 1. Headline KPI: match infection rate
--    Definition: share of matches containing at least one player later confirmed
--    cheating (appeal-upheld). This is the number that tells you whether the
--    ecosystem is improving, not the raw ban count.
-- ---------------------------------------------------------------------------
WITH confirmed AS (
    SELECT DISTINCT player_id
    FROM enforcement
    WHERE action IN ('ban', 'hwid_ban')
      AND (appeal_outcome IS NULL OR appeal_outcome = 'upheld')
),
match_flags AS (
    SELECT m.match_id,
           m.started_at::date AS day,
           MAX(CASE WHEN c.player_id IS NOT NULL THEN 1 ELSE 0 END) AS infected
    FROM matches m
    JOIN match_players mp ON mp.match_id = m.match_id
    LEFT JOIN confirmed c ON c.player_id = mp.player_id
    GROUP BY m.match_id, m.started_at::date
)
SELECT day,
       COUNT(*)                                        AS matches_played,
       SUM(infected)                                   AS infected_matches,
       ROUND(100.0 * SUM(infected) / COUNT(*), 3)      AS infection_rate_pct
FROM match_flags
GROUP BY day
ORDER BY day;

-- ---------------------------------------------------------------------------
-- 2. Kill-rate outliers within a rank tier
--    Cohorting by tier is what makes this usable: a Predator's kill rate is not
--    comparable to a Bronze's. z-score against the tier mean/std.
-- ---------------------------------------------------------------------------
WITH per_match AS (
    SELECT mp.player_id,
           p.rank_tier,
           mp.match_id,
           mp.kills * 60000.0 / NULLIF(mp.survival_ms, 0) AS kills_per_min
    FROM match_players mp
    JOIN players p ON p.player_id = mp.player_id
    WHERE mp.survival_ms > 60000        -- ignore hot-drops
),
tier_stats AS (
    SELECT rank_tier,
           AVG(kills_per_min) AS mu,
           STDDEV_SAMP(kills_per_min) AS sigma,
           COUNT(*) AS n
    FROM per_match
    GROUP BY rank_tier
    HAVING COUNT(*) >= 100
)
SELECT pm.player_id,
       pm.rank_tier,
       COUNT(*) AS matches,
       ROUND(AVG(pm.kills_per_min), 3) AS avg_kpm,
       ROUND(MAX((pm.kills_per_min - ts.mu) / NULLIF(ts.sigma, 0)), 2) AS max_z
FROM per_match pm
JOIN tier_stats ts ON ts.rank_tier = pm.rank_tier
GROUP BY pm.player_id, pm.rank_tier, ts.mu, ts.sigma
HAVING COUNT(*) >= 5
   AND MAX((pm.kills_per_min - ts.mu) / NULLIF(ts.sigma, 0)) > 4
ORDER BY max_z DESC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 3. Headshot-rate outliers (long-range accuracy)
--    Aimbots and recoil scripts show up as an impossible tail here, especially
--    on high-recoil weapons at range.
-- ---------------------------------------------------------------------------
SELECT mp.player_id,
       SUM(mp.shots_hit)  AS hits,
       SUM(mp.headshots)  AS headshots,
       ROUND(1.0 * SUM(mp.headshots) / NULLIF(SUM(mp.shots_hit), 0), 4) AS hs_rate,
       ROUND(AVG(mp.damage), 1) AS avg_damage
FROM match_players mp
WHERE mp.shots_hit >= 50
GROUP BY mp.player_id
HAVING SUM(mp.shots_hit) >= 200
   AND 1.0 * SUM(mp.headshots) / NULLIF(SUM(mp.shots_hit), 0) > 0.65
ORDER BY hs_rate DESC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 4. Triggerbot signature: fire latency mass at the bottom of the distribution
--    Needs input_events with target_enter / fire markers.
-- ---------------------------------------------------------------------------
WITH latencies AS (
    SELECT e.player_id,
           f.t_ms - e.t_ms AS fire_latency_ms
    FROM input_events e
    JOIN input_events f
      ON f.player_id = e.player_id
     AND f.match_id  = e.match_id
     AND f.event     = 'fire'
     AND f.t_ms >= e.t_ms
     AND f.t_ms <  e.t_ms + 1000
    WHERE e.event = 'target_enter'
),
player_stats AS (
    SELECT player_id,
           COUNT(*) AS n_engagements,
           AVG(CASE WHEN fire_latency_ms < 80 THEN 1.0 ELSE 0 END) AS frac_sub80ms,
           PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY fire_latency_ms) AS p10_latency
    FROM latencies
    GROUP BY player_id
    HAVING COUNT(*) >= 30
)
SELECT * FROM player_stats
WHERE frac_sub80ms > 0.35
ORDER BY frac_sub80ms DESC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 5. Recoil-script regularity
--    Scripted compensation is deterministic; human compensation is not. Compare
--    per-player per-shot mouse-dy variance against the weapon cohort.
-- ---------------------------------------------------------------------------
WITH shot_vectors AS (
    SELECT e.player_id,
           e.match_id,
           e.t_ms,
           e.weapon_id,
           SUM(CASE WHEN s.event = 'move' THEN s.mouse_dy ELSE 0 END) AS comp_dy
    FROM input_events e
    LEFT JOIN input_events s
      ON s.player_id = e.player_id
     AND s.match_id  = e.match_id
     AND s.t_ms BETWEEN e.t_ms AND e.t_ms + 80
    WHERE e.event = 'fire'
    GROUP BY e.player_id, e.match_id, e.t_ms, e.weapon_id
),
per_player AS (
    SELECT player_id,
           weapon_id,
           COUNT(*) AS shots,
           AVG(comp_dy) AS mean_dy,
           STDDEV_SAMP(comp_dy) AS sd_dy
    FROM shot_vectors
    GROUP BY player_id, weapon_id
    HAVING COUNT(*) >= 200
)
SELECT player_id,
       weapon_id,
       shots,
       ROUND(mean_dy, 4) AS mean_comp_dy,
       ROUND(sd_dy, 4)   AS sd_comp_dy,
       ROUND(1.0 * sd_dy / NULLIF(ABS(mean_dy), 0), 4) AS coeff_var
FROM per_player
WHERE ABS(mean_dy) > 0.05
  AND 1.0 * sd_dy / NULLIF(ABS(mean_dy), 0) < 0.12      -- suspiciously consistent
ORDER BY coeff_var ASC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 6. Boosting / deranking: asymmetric duo performance
--    One account performs far above its tier while its frequent partner performs
--    far below, and the pair queues together constantly.
-- ---------------------------------------------------------------------------
WITH duos AS (
    SELECT a.player_id AS booster,
           b.player_id AS customer
    FROM match_players a
    JOIN match_players b
      ON b.match_id = a.match_id
     AND b.squad_id = a.squad_id
     AND b.player_id <> a.player_id
    GROUP BY a.player_id, b.player_id
    HAVING COUNT(*) >= 20            -- persistent duo
),
perf AS (
    SELECT mp.player_id,
           AVG(mp.kills + mp.assists) AS avg_ka,
           AVG(mp.damage) AS avg_damage,
           AVG(mp.rp_delta) AS avg_rp
    FROM match_players mp
    GROUP BY mp.player_id
)
SELECT d.booster, d.customer,
       ROUND(p1.avg_ka, 2)     AS booster_ka,
       ROUND(p2.avg_ka, 2)     AS customer_ka,
       ROUND(p1.avg_rp, 1)     AS booster_rp,
       ROUND(p2.avg_rp, 1)     AS customer_rp
FROM duos d
JOIN perf p1 ON p1.player_id = d.booster
JOIN perf p2 ON p2.player_id = d.customer
WHERE p1.avg_ka > 2.5 * NULLIF(p2.avg_ka, 0)
  AND p2.avg_rp > 0
ORDER BY booster_ka DESC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 7. Smurfing: skill far above account age / level
-- ---------------------------------------------------------------------------
SELECT p.player_id,
       p.account_level,
       DATE_PART('day', NOW() - p.account_created) AS account_age_days,
       ROUND(AVG(mp.kills), 2) AS avg_kills,
       ROUND(AVG(mp.damage), 1) AS avg_damage,
       MAX(p.rank_tier) AS tier
FROM players p
JOIN match_players mp ON mp.player_id = p.player_id
WHERE DATE_PART('day', NOW() - p.account_created) < 30
GROUP BY p.player_id, p.account_level, p.account_created
HAVING COUNT(mp.match_id) >= 20
   AND AVG(mp.kills) > 6
ORDER BY avg_kills DESC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 8. Account sharing / piloting: impossible travel + input signature drift
-- ---------------------------------------------------------------------------
WITH travel AS (
    SELECT s1.player_id,
           s1.ip_country AS from_country,
           s2.ip_country AS to_country,
           s1.ended_at   AS left_at,
           s2.started_at AS arrived_at,
           EXTRACT(EPOCH FROM (s2.started_at - s1.ended_at)) / 60.0 AS gap_minutes
    FROM sessions s1
    JOIN sessions s2
      ON s2.player_id = s1.player_id
     AND s2.started_at > s1.ended_at
     AND s2.started_at = (
           SELECT MIN(s3.started_at) FROM sessions s3
           WHERE s3.player_id = s1.player_id AND s3.started_at > s1.ended_at)
)
SELECT player_id, from_country, to_country,
       ROUND(gap_minutes, 1) AS gap_minutes
FROM travel
WHERE from_country IS DISTINCT FROM to_country
  AND gap_minutes < 240
ORDER BY gap_minutes ASC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 9. HWID ban evasion: a "new" player on previously banned hardware
-- ---------------------------------------------------------------------------
SELECT p.player_id,
       p.account_created,
       h.fingerprint,
       h.first_seen AS hw_first_seen,
       b.player_id  AS prior_banned_player,
       b.banned_at
FROM players p
JOIN player_hw ph ON ph.player_id = p.player_id
JOIN hardware  h  ON h.hw_id = ph.hw_id
JOIN player_hw ph2 ON ph2.hw_id = h.hw_id
JOIN players   b   ON b.player_id = ph2.player_id AND b.is_banned
WHERE p.player_id <> b.player_id
  AND p.account_created > b.banned_at
  AND NOT p.is_banned
ORDER BY p.account_created DESC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 10. Hardware fingerprint inconsistency (spoofing indicator)
--     A genuine machine has consistent components across sessions. A spoofer
--     churns identifiers independently, so the fingerprint's component set
--     disagrees with its own history and with its MAC/SMBIOS vendors.
-- ---------------------------------------------------------------------------
SELECT h.hw_id,
       h.fingerprint,
       COUNT(DISTINCT h.mb_uuid)     AS distinct_mb_uuid,
       COUNT(DISTINCT h.disk_serial) AS distinct_disk_serial,
       COUNT(DISTINCT h.mac_vendor)  AS distinct_mac_vendors,
       MIN(h.first_seen)             AS first_seen,
       MAX(h.last_seen)              AS last_seen
FROM hardware h
GROUP BY h.hw_id, h.fingerprint
HAVING COUNT(DISTINCT h.mb_uuid) > 1
    OR COUNT(DISTINCT h.disk_serial) > 2
    OR COUNT(DISTINCT h.mac_vendor) > 2
ORDER BY distinct_disk_serial DESC
LIMIT 200;

-- ---------------------------------------------------------------------------
-- 11. Enforcement wave efficacy
--     Infection rate and report volume in the 14 days before vs. after a wave.
-- ---------------------------------------------------------------------------
WITH wave AS (
    SELECT wave_id, MIN(ts) AS wave_start, MAX(ts) AS wave_end
    FROM enforcement
    WHERE wave_id IS NOT NULL
    GROUP BY wave_id
),
confirmed AS (
    SELECT DISTINCT player_id FROM enforcement
    WHERE action IN ('ban','hwid_ban') AND appeal_outcome IS DISTINCT FROM 'overturned'
),
infected AS (
    SELECT m.started_at::date AS day,
           MAX(CASE WHEN c.player_id IS NOT NULL THEN 1 ELSE 0 END) AS infected
    FROM matches m
    JOIN match_players mp ON mp.match_id = m.match_id
    LEFT JOIN confirmed c ON c.player_id = mp.player_id
    GROUP BY m.match_id, m.started_at::date
)
SELECT w.wave_id,
       'before' AS period,
       ROUND(100.0 * SUM(i.infected) / COUNT(*), 3) AS infection_rate_pct
FROM wave w JOIN infected i ON i.day BETWEEN w.wave_start::date - 14 AND w.wave_start::date - 1
GROUP BY w.wave_id
UNION ALL
SELECT w.wave_id,
       'after' AS period,
       ROUND(100.0 * SUM(i.infected) / COUNT(*), 3) AS infection_rate_pct
FROM wave w JOIN infected i ON i.day BETWEEN w.wave_end::date AND w.wave_end::date + 14
GROUP BY w.wave_id
ORDER BY wave_id, period;

-- ---------------------------------------------------------------------------
-- 12. Review queue triage: rank players by independent evidence sources
--     The point is breadth of evidence, not a single extreme number.
-- ---------------------------------------------------------------------------
WITH evidence AS (
    SELECT player_id, 'kill_rate'   AS signal FROM match_players GROUP BY player_id
    HAVING AVG(kills) > 8
    UNION ALL
    SELECT player_id, 'hs_rate' FROM match_players
    GROUP BY player_id HAVING 1.0 * SUM(headshots) / NULLIF(SUM(shots_hit),0) > 0.6
    UNION ALL
    SELECT player_id, 'new_account_high_skill' FROM players p
    JOIN match_players mp ON mp.player_id = p.player_id
    WHERE DATE_PART('day', NOW() - p.account_created) < 14
    GROUP BY p.player_id, p.account_created
    HAVING COUNT(*) >= 15 AND AVG(mp.kills) > 6
)
SELECT e.player_id,
       COUNT(DISTINCT e.signal) AS independent_signals,
       STRING_AGG(DISTINCT e.signal, ', ') AS signals
FROM evidence e
GROUP BY e.player_id
HAVING COUNT(DISTINCT e.signal) >= 2
ORDER BY independent_signals DESC
LIMIT 500;
