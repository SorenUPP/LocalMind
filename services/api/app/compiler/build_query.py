import duckdb
from app.schemas.ast import QueryPlan

OP_MAP = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}

# Self-contained analyses (outlier, market_share, pareto, active_day_velocity,
# top_contributor, share_of_total, group_deviation, consistency) - see
# compiler/validate.py for why these can't mix with the
# filter/time_bucket/aggregate/window/sort/limit pipeline.
ANALYSIS_KINDS = {
    "outlier", "market_share", "pareto", "active_day_velocity", "top_contributor",
    "share_of_total", "group_deviation", "consistency",
}


def quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _build_filter_clause(node, params: list) -> list[str]:
    where_clauses = []
    for p in node.predicates:
        col = quote_identifier(p.column)
        if p.op == "contains":
            where_clauses.append(f"{col} ILIKE ?")
            params.append(f"%{p.value}%")
        elif p.op == "in":
            placeholders = ",".join(["?"] * len(p.value))
            where_clauses.append(f"{col} IN ({placeholders})")
            params.extend(p.value)
        else:
            where_clauses.append(f"{col} {OP_MAP[p.op]} ?")
            params.append(p.value)
    return where_clauses


def build_and_execute(con: duckdb.DuckDBPyConnection, plan: QueryPlan):
    analysis_node = next((node for node in plan.nodes if node.kind in ANALYSIS_KINDS), None)
    if analysis_node is not None:
        return _execute_analysis_plan(con, plan, analysis_node)
    return _execute_pipeline_plan(con, plan)


def _execute_pipeline_plan(con: duckdb.DuckDBPyConnection, plan: QueryPlan):
    params = []
    where_clauses = []
    time_buckets: dict[str, str] = {}
    group_selects, group_expressions, metrics_sql = [], [], []
    window_metrics = []
    order_clauses = []
    limit_sql = ""

    for node in plan.nodes:
        if node.kind == "filter":
            where_clauses.extend(_build_filter_clause(node, params))
        elif node.kind == "time_bucket":
            time_buckets[node.alias] = f"DATE_TRUNC('{node.granularity}', {quote_identifier(node.column)})"
        elif node.kind == "aggregate":
            for group in node.group_by:
                expression = time_buckets.get(group.name, quote_identifier(group.name))
                group_selects.append(f"{expression} AS {quote_identifier(group.name)}" if group.name in time_buckets else expression)
                group_expressions.append(expression)
            metrics_sql = [f"{metric.fn.upper()}({quote_identifier(metric.column)}) AS {quote_identifier(metric.alias)}" for metric in node.metrics]
        elif node.kind == "window":
            window_metrics = node.metrics
        elif node.kind == "sort":
            order_clauses = [f"{quote_identifier(key.column)} {key.direction.upper()}" for key in node.keys]
        elif node.kind == "limit":
            limit_sql = f"LIMIT {int(node.count)}"

    select_cols = ", ".join(group_selects + metrics_sql) if metrics_sql else "*"
    sql = f"SELECT {select_cols} FROM {quote_identifier(plan.dataset)}"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    if group_expressions:
        sql += " GROUP BY " + ", ".join(group_expressions)
    if window_metrics:
        calculations = []
        for metric in window_metrics:
            value = quote_identifier(metric.column)
            partition = ", ".join(quote_identifier(column.name) for column in metric.partition_by)
            order = quote_identifier(metric.order_by.name)
            over = f"OVER ({f'PARTITION BY {partition} ' if partition else ''}ORDER BY {order})"
            previous_value = f"LAG({value}) {over}"
            calculations.append(
                f"(({value} - {previous_value}) / NULLIF({previous_value}, 0)) * 100 AS {quote_identifier(metric.alias)}"
            )
        sql = f"WITH aggregated AS ({sql}) SELECT aggregated.*, {', '.join(calculations)} FROM aggregated"
    if order_clauses:
        sql += " ORDER BY " + ", ".join(order_clauses)
    if not limit_sql:
        limit_sql = "LIMIT 1000"
    sql += " " + limit_sql

    return con.execute(sql, params).fetchdf()


def _build_outlier_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Flags rows whose value_column is more than `threshold` standard
    deviations from the mean within its group_by partition (z-score outliers)."""
    value_col = quote_identifier(node.value_column)
    group_cols = [quote_identifier(g.name) for g in node.group_by]
    partition = f"PARTITION BY {', '.join(group_cols)}" if group_cols else ""
    select_cols = ", ".join(group_cols + [value_col]) if group_cols else value_col
    z_alias = quote_identifier(node.z_score_alias)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
        WITH scored AS (
            SELECT {select_cols},
                ({value_col} - AVG({value_col}) OVER ({partition}))
                    / NULLIF(STDDEV_POP({value_col}) OVER ({partition}), 0) AS {z_alias}
            FROM __TABLE__
            {where_sql}
        )
        SELECT * FROM scored WHERE ABS({z_alias}) > ?
    """
    return sql, filter_params + [node.threshold]


def _build_market_share_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Compares each group's share of total revenue on start_date vs end_date."""
    group_col = quote_identifier(node.group_by.name)
    date_col = quote_identifier(node.date_column)
    revenue_col = quote_identifier(node.revenue_column)
    extra_where = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"""
        WITH start_rev AS (
            SELECT {group_col} AS grp, SUM({revenue_col}) AS revenue
            FROM __TABLE__ WHERE {date_col} = ?{extra_where}
            GROUP BY {group_col}
        ),
        end_rev AS (
            SELECT {group_col} AS grp, SUM({revenue_col}) AS revenue
            FROM __TABLE__ WHERE {date_col} = ?{extra_where}
            GROUP BY {group_col}
        ),
        totals AS (
            SELECT (SELECT SUM(revenue) FROM start_rev) AS start_total,
                   (SELECT SUM(revenue) FROM end_rev) AS end_total
        )
        SELECT
            COALESCE(start_rev.grp, end_rev.grp) AS {group_col},
            100.0 * start_rev.revenue / NULLIF(totals.start_total, 0) AS {quote_identifier(node.start_alias)},
            100.0 * end_rev.revenue / NULLIF(totals.end_total, 0) AS {quote_identifier(node.end_alias)},
            (100.0 * end_rev.revenue / NULLIF(totals.end_total, 0))
                - (100.0 * start_rev.revenue / NULLIF(totals.start_total, 0)) AS {quote_identifier(node.change_alias)}
        FROM start_rev
        FULL OUTER JOIN end_rev ON start_rev.grp = end_rev.grp
        CROSS JOIN totals
    """
    params = [node.start_date] + filter_params + [node.end_date] + filter_params
    return sql, params


def _build_pareto_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Finds how many top transactions (by value_column) account for
    threshold_percent of the total value (classic 80/20-style analysis)."""
    value_col = quote_identifier(node.value_column)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
        WITH ranked AS (
            SELECT {value_col},
                ROW_NUMBER() OVER (ORDER BY {value_col} DESC) AS rn,
                SUM({value_col}) OVER (ORDER BY {value_col} DESC) AS running_total,
                SUM({value_col}) OVER () AS grand_total,
                COUNT(*) OVER () AS total_count
            FROM __TABLE__
            {where_sql}
        ),
        cumulative AS (
            SELECT *, 100.0 * running_total / NULLIF(grand_total, 0) AS cumulative_pct
            FROM ranked
        )
        SELECT
            MIN(rn) FILTER (WHERE cumulative_pct >= ?) AS {quote_identifier(node.count_alias)},
            100.0 * MIN(rn) FILTER (WHERE cumulative_pct >= ?) / NULLIF(MAX(total_count), 0)
                AS {quote_identifier(node.transaction_percentage_alias)},
            MIN(cumulative_pct) FILTER (WHERE cumulative_pct >= ?) AS {quote_identifier(node.revenue_percentage_alias)}
        FROM cumulative
    """
    params = filter_params + [node.threshold_percent] * 3
    return sql, params


def _build_active_day_velocity_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Total revenue, count of distinct active days, and revenue-per-active-day
    per group."""
    group_col = quote_identifier(node.group_by.name)
    date_col = quote_identifier(node.date_column)
    revenue_col = quote_identifier(node.revenue_column)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
        SELECT {group_col},
            SUM({revenue_col}) AS {quote_identifier(node.total_alias)},
            COUNT(DISTINCT {date_col}) AS {quote_identifier(node.active_days_alias)},
            SUM({revenue_col}) / NULLIF(COUNT(DISTINCT {date_col}), 0) AS {quote_identifier(node.velocity_alias)}
        FROM __TABLE__
        {where_sql}
    """
    if node.kind == "active_day_velocity":
        sql += f" GROUP BY {group_col}"
    return sql, filter_params


def _build_top_contributor_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Finds the outer group with the largest total value_column (e.g. the
    highest-revenue day), then breaks that single outer group down by
    inner_group_by (e.g. region), returning each inner group's total and its
    share of the outer group's total."""
    outer_col = quote_identifier(node.outer_group_by.name)
    inner_col = quote_identifier(node.inner_group_by.name)
    value_col = quote_identifier(node.value_column)
    outer_alias = quote_identifier(node.outer_value_alias)
    inner_alias = quote_identifier(node.inner_value_alias)
    share_alias = quote_identifier(node.share_alias)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
        WITH grouped AS (
            SELECT {outer_col} AS outer_group, {inner_col} AS inner_group,
                SUM({value_col}) AS {inner_alias}
            FROM __TABLE__
            {where_sql}
            GROUP BY {outer_col}, {inner_col}
        ),
        with_outer_totals AS (
            SELECT outer_group, inner_group, {inner_alias},
                SUM({inner_alias}) OVER (PARTITION BY outer_group) AS {outer_alias}
            FROM grouped
        ),
        ranked AS (
            SELECT outer_group, inner_group, {inner_alias}, {outer_alias},
                RANK() OVER (ORDER BY {outer_alias} DESC) AS outer_rank
            FROM with_outer_totals
        )
        SELECT
            outer_group AS {outer_col},
            inner_group AS {inner_col},
            {inner_alias},
            {outer_alias},
            100.0 * {inner_alias} / NULLIF({outer_alias}, 0) AS {share_alias}
        FROM ranked
        WHERE outer_rank = 1
    """
    return sql, filter_params


def _build_share_of_total_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Each group's share of the grand total of value_column. If change_percent
    is supplied, also projects what a change of that size *within a single
    group* would do to that group's total and to the grand total (used for
    "what if region X changed by N%" scenario questions - the caller picks
    which group via sort/limit, e.g. sort by the total desc + limit 1 to
    evaluate the scenario against the largest group)."""
    group_col = quote_identifier(node.group_by.name)
    value_col = quote_identifier(node.value_column)
    total_alias = quote_identifier(node.total_alias)
    grand_total_alias = quote_identifier(node.grand_total_alias)
    share_alias = quote_identifier(node.share_alias)
    projected_total_alias = quote_identifier(node.projected_total_alias)
    projected_grand_total_alias = quote_identifier(node.projected_grand_total_alias)
    impact_alias = quote_identifier(node.impact_alias)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params = list(filter_params)

    if node.change_percent is not None:
        params.extend([node.change_percent, node.change_percent, node.change_percent])
        projected_exprs = f"""
            group_total * (1 + ? / 100.0) AS {projected_total_alias},
            grand_total + (group_total * (1 + ? / 100.0) - group_total) AS {projected_grand_total_alias},
            100.0 * (group_total * (1 + ? / 100.0) - group_total) / NULLIF(grand_total, 0) AS {impact_alias}
        """
    else:
        projected_exprs = f"""
            NULL AS {projected_total_alias},
            NULL AS {projected_grand_total_alias},
            NULL AS {impact_alias}
        """

    sql = f"""
        WITH grouped AS (
            SELECT {group_col} AS grp, SUM({value_col}) AS group_total
            FROM __TABLE__
            {where_sql}
            GROUP BY {group_col}
        ),
        totals AS (
            SELECT *, SUM(group_total) OVER () AS grand_total
            FROM grouped
        )
        SELECT
            grp AS {group_col},
            group_total AS {total_alias},
            grand_total AS {grand_total_alias},
            100.0 * group_total / NULLIF(grand_total, 0) AS {share_alias},
            {projected_exprs}
        FROM totals
    """
    return sql, params


def _build_group_deviation_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Sums value_column per group, then z-scores each group's *total* against
    the distribution of all group totals (not row-level, unlike outlier),
    labeling each group as significantly above/below/in line with the
    cross-group average."""
    group_col = quote_identifier(node.group_by.name)
    value_col = quote_identifier(node.value_column)
    total_alias = quote_identifier(node.total_alias)
    mean_alias = quote_identifier(node.mean_alias)
    z_alias = quote_identifier(node.z_score_alias)
    significance_alias = quote_identifier(node.significance_alias)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params = list(filter_params) + [node.threshold, node.threshold]
    sql = f"""
        WITH grouped AS (
            SELECT {group_col} AS grp, SUM({value_col}) AS group_total
            FROM __TABLE__
            {where_sql}
            GROUP BY {group_col}
        ),
        stats AS (
            SELECT *,
                AVG(group_total) OVER () AS group_mean,
                STDDEV_POP(group_total) OVER () AS group_stddev
            FROM grouped
        ),
        scored AS (
            SELECT *, (group_total - group_mean) / NULLIF(group_stddev, 0) AS z
            FROM stats
        )
        SELECT
            grp AS {group_col},
            group_total AS {total_alias},
            group_mean AS {mean_alias},
            z AS {z_alias},
            CASE
                WHEN z > ? THEN 'significantly above average'
                WHEN z < -? THEN 'significantly below average'
                ELSE 'in line with average'
            END AS {significance_alias}
        FROM scored
    """
    return sql, params


def _build_consistency_sql(node, where_clauses: list[str], filter_params: list) -> tuple[str, list]:
    """Buckets revenue by group and time period, then reports each group's
    total revenue alongside its period-to-period consistency (coefficient of
    variation). consistency_score discounts total_revenue by its own CV, so a
    higher score reflects a group that is both large and stable - sort desc +
    limit 1 to answer "which group has the strongest combination of high
    revenue and consistent performance"."""
    group_col = quote_identifier(node.group_by.name)
    date_col = quote_identifier(node.date_column)
    revenue_col = quote_identifier(node.revenue_column)
    total_alias = quote_identifier(node.total_alias)
    period_count_alias = quote_identifier(node.period_count_alias)
    avg_period_alias = quote_identifier(node.avg_period_alias)
    stddev_period_alias = quote_identifier(node.stddev_period_alias)
    cv_alias = quote_identifier(node.coefficient_of_variation_alias)
    score_alias = quote_identifier(node.consistency_score_alias)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    # node.granularity is a validated Literal["day","month"], not user-supplied
    # free text, so it is safe to interpolate directly.
    period_expr = f"DATE_TRUNC('{node.granularity}', {date_col})"
    sql = f"""
        WITH period_bucket AS (
            SELECT {group_col} AS grp, {period_expr} AS period, SUM({revenue_col}) AS period_revenue
            FROM __TABLE__
            {where_sql}
            GROUP BY {group_col}, {period_expr}
        ),
        summary AS (
            SELECT
                grp,
                SUM(period_revenue) AS total_revenue,
                COUNT(*) AS period_count,
                AVG(period_revenue) AS avg_period_revenue,
                STDDEV_POP(period_revenue) AS stddev_period_revenue
            FROM period_bucket
            GROUP BY grp
        )
        SELECT
            grp AS {group_col},
            total_revenue AS {total_alias},
            period_count AS {period_count_alias},
            avg_period_revenue AS {avg_period_alias},
            stddev_period_revenue AS {stddev_period_alias},
            100.0 * stddev_period_revenue / NULLIF(avg_period_revenue, 0) AS {cv_alias},
            total_revenue / (1 + (100.0 * stddev_period_revenue / NULLIF(avg_period_revenue, 0)) / 100.0) AS {score_alias}
        FROM summary
    """
    return sql, filter_params


_ANALYSIS_BUILDERS = {
    "outlier": _build_outlier_sql,
    "market_share": _build_market_share_sql,
    "pareto": _build_pareto_sql,
    "active_day_velocity": _build_active_day_velocity_sql,
    "top_contributor": _build_top_contributor_sql,
    "share_of_total": _build_share_of_total_sql,
    "group_deviation": _build_group_deviation_sql,
    "consistency": _build_consistency_sql,
}


def _execute_analysis_plan(con: duckdb.DuckDBPyConnection, plan: QueryPlan, analysis_node):
    filter_node = next((n for n in plan.nodes if n.kind == "filter"), None)
    filter_params: list = []
    where_clauses = _build_filter_clause(filter_node, filter_params) if filter_node else []

    table = quote_identifier(plan.dataset)
    build_fn = _ANALYSIS_BUILDERS[analysis_node.kind]
    sql, params = build_fn(analysis_node, where_clauses, filter_params)
    sql = sql.replace("__TABLE__", table)

    sort_node = next((n for n in plan.nodes if n.kind == "sort"), None)
    limit_node = next((n for n in plan.nodes if n.kind == "limit"), None)
    sql = f"SELECT * FROM ({sql}) AS analysis_result"
    if sort_node:
        order_clauses = [f"{quote_identifier(key.column)} {key.direction.upper()}" for key in sort_node.keys]
        sql += " ORDER BY " + ", ".join(order_clauses)
    sql += f" LIMIT {int(limit_node.count)}" if limit_node else " LIMIT 1000"

    return con.execute(sql, params).fetchdf()
