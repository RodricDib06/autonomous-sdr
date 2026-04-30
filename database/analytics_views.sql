-- AutonomousSDR Analytics Views
-- Run: psql postgresql://sdr_user:sdrpassword@localhost:5433/sdr_db -f database/analytics_views.sql

CREATE OR REPLACE VIEW vw_lead_pipeline AS
SELECT
    l.id                        AS lead_id,
    l.name                      AS lead_name,
    l.email                     AS lead_email,
    l.company                   AS lead_company,
    l.source                    AS lead_source,
    l.created_at                AS received_at,
    l.status                    AS pipeline_status,
    e.job_title,
    e.seniority,
    e.company_size,
    e.industry,
    e.revenue_estimate,
    e.tech_stack,
    e.confidence                AS enrichment_confidence,
    e.enrichment_source,
    v.analysis_verdict,
    v.final_verdict,
    v.confidence_score          AS verdict_confidence,
    v.icp_match,
    v.validated,
    v.bant_scores,
    v.flags,
    EXTRACT(EPOCH FROM (v.created_at - l.created_at))
                                AS processing_seconds
FROM leads l
LEFT JOIN enrichments e ON e.lead_id = l.id
LEFT JOIN verdicts v ON v.lead_id = l.id;


CREATE OR REPLACE VIEW vw_daily_summary AS
SELECT
    DATE(l.created_at)          AS day,
    COUNT(*)                    AS total_leads,
    COUNT(CASE WHEN v.final_verdict = 'Hot'  THEN 1 END) AS hot_leads,
    COUNT(CASE WHEN v.final_verdict = 'Warm' THEN 1 END) AS warm_leads,
    COUNT(CASE WHEN v.final_verdict = 'Cold' THEN 1 END) AS cold_leads,
    ROUND(AVG(v.confidence_score)::numeric, 2)           AS avg_confidence,
    ROUND(AVG(EXTRACT(EPOCH FROM (v.created_at - l.created_at)))::numeric, 1)
                                AS avg_processing_seconds,
    COUNT(CASE WHEN v.icp_match = true THEN 1 END)       AS icp_matches
FROM leads l
LEFT JOIN verdicts v ON v.lead_id = l.id
GROUP BY DATE(l.created_at)
ORDER BY day DESC;


CREATE OR REPLACE VIEW vw_industry_performance AS
SELECT
    e.industry,
    COUNT(*)                    AS total_leads,
    COUNT(CASE WHEN v.final_verdict = 'Hot'  THEN 1 END) AS hot_count,
    COUNT(CASE WHEN v.final_verdict = 'Warm' THEN 1 END) AS warm_count,
    COUNT(CASE WHEN v.final_verdict = 'Cold' THEN 1 END) AS cold_count,
    ROUND(
        COUNT(CASE WHEN v.final_verdict = 'Hot' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0),
        1
    )                           AS hot_rate_pct,
    ROUND(AVG(v.confidence_score)::numeric, 2) AS avg_confidence
FROM enrichments e
LEFT JOIN verdicts v ON v.lead_id = e.lead_id
GROUP BY e.industry
ORDER BY hot_count DESC;


CREATE OR REPLACE VIEW vw_agent_performance AS
SELECT
    agent_name,
    COUNT(*)                    AS total_runs,
    COUNT(CASE WHEN success = true  THEN 1 END) AS successful_runs,
    COUNT(CASE WHEN success = false THEN 1 END) AS failed_runs,
    ROUND(AVG(duration_ms)::numeric, 0)         AS avg_duration_ms,
    MAX(duration_ms)                            AS max_duration_ms,
    ROUND(
        COUNT(CASE WHEN success = true THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0),
        1
    )                           AS success_rate_pct
FROM agent_logs
GROUP BY agent_name
ORDER BY agent_name;


CREATE OR REPLACE VIEW vw_confidence_distribution AS
SELECT
    final_verdict,
    CASE
        WHEN confidence_score >= 0.9  THEN '0.9 - 1.0 (Very High)'
        WHEN confidence_score >= 0.75 THEN '0.75 - 0.9 (High)'
        WHEN confidence_score >= 0.6  THEN '0.6 - 0.75 (Medium)'
        WHEN confidence_score >= 0.4  THEN '0.4 - 0.6 (Low)'
        ELSE '0.0 - 0.4 (Very Low)'
    END                         AS confidence_bucket,
    COUNT(*)                    AS lead_count
FROM verdicts
WHERE confidence_score IS NOT NULL
GROUP BY final_verdict, confidence_bucket
ORDER BY final_verdict, confidence_bucket;


CREATE OR REPLACE VIEW vw_seniority_verdict_matrix AS
SELECT
    e.seniority,
    v.final_verdict,
    COUNT(*)                    AS lead_count,
    ROUND(AVG(v.confidence_score)::numeric, 2) AS avg_confidence
FROM enrichments e
LEFT JOIN verdicts v ON v.lead_id = e.lead_id
WHERE e.seniority IS NOT NULL
  AND v.final_verdict IS NOT NULL
GROUP BY e.seniority, v.final_verdict
ORDER BY e.seniority, v.final_verdict;
