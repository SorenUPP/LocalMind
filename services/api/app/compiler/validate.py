from app.schemas.ast import QueryPlan


class ValidationError(Exception):
    def __init__(self, errors: list[dict]):
        self.errors = errors


# Pipeline nodes compose sequentially into one SELECT: filter -> time_bucket ->
# aggregate -> window -> sort -> limit.
PIPELINE_NODE_ORDER = {"filter": 0, "time_bucket": 1, "aggregate": 2, "window": 3, "sort": 4, "limit": 5}

# Analysis nodes (outlier, market_share, pareto, active_day_velocity,
# top_contributor, share_of_total, group_deviation, consistency) are
# self-contained, pre-built analyses (each already aggregates internally), so
# they can't be combined with time_bucket/aggregate/window. They may only be
# preceded by an optional "filter" and followed by "sort"/"limit".
ANALYSIS_NODE_KINDS = {
    "outlier", "market_share", "pareto", "active_day_velocity", "top_contributor",
    "share_of_total", "group_deviation", "consistency",
}
PIPELINE_ONLY_KINDS = {"time_bucket", "aggregate", "window"}
SINGLETON_KINDS = {"time_bucket", "aggregate", "window", "sort", "limit"} | ANALYSIS_NODE_KINDS

NODE_ORDER = {**PIPELINE_NODE_ORDER, **{kind: 1 for kind in ANALYSIS_NODE_KINDS}}


def _check_unknown_columns(errors: list[dict], path: str, columns: list[str], allowed: set[str]) -> None:
    for column in columns:
        if column not in allowed:
            errors.append({"path": path, "code": "unknown_column", "allowed": sorted(allowed)})


def semantic_validate(plan: QueryPlan, allowed_columns: set[str], expected_dataset: str | None = None) -> None:
    errors: list[dict] = []

    if expected_dataset and plan.dataset != expected_dataset:
        errors.append({"path": "dataset", "code": "dataset_mismatch", "allowed": [expected_dataset]})

    present_kinds = {node.kind for node in plan.nodes}
    if present_kinds & ANALYSIS_NODE_KINDS and present_kinds & PIPELINE_ONLY_KINDS:
        errors.append({
            "path": "nodes",
            "code": "analysis_node_combined_with_pipeline",
            "message": (
                "Analysis nodes (outlier/market_share/pareto/active_day_velocity/"
                "top_contributor/share_of_total/group_deviation/consistency) already "
                "aggregate internally and cannot be combined with time_bucket, "
                "aggregate, or window nodes."
            ),
        })

    previous_order = -1
    seen_singletons: set[str] = set()
    time_bucket_aliases: set[str] = set()
    aggregate_aliases: set[str] = set()
    window_aliases: set[str] = set()
    analysis_aliases: set[str] = set()

    for i, node in enumerate(plan.nodes):
        order = NODE_ORDER.get(node.kind)
        if order is None:
            errors.append({"path": f"nodes.{i}", "code": "unsupported_node", "kind": node.kind})
            continue
        if order < previous_order:
            errors.append({"path": f"nodes.{i}", "code": "invalid_node_order"})
        previous_order = order

        if node.kind in SINGLETON_KINDS:
            if node.kind in seen_singletons:
                errors.append({"path": f"nodes.{i}", "code": "duplicate_node", "kind": node.kind})
            seen_singletons.add(node.kind)

        if node.kind == "filter":
            for j, p in enumerate(node.predicates):
                if p.column not in allowed_columns:
                    errors.append({"path": f"nodes.{i}.predicates.{j}.column", "code": "unknown_column", "allowed": sorted(allowed_columns)})
                if p.op == "in" and (not isinstance(p.value, list) or not p.value):
                    errors.append({"path": f"nodes.{i}.predicates.{j}.value", "code": "non_empty_list_required"})
                if p.op == "contains" and not isinstance(p.value, str):
                    errors.append({"path": f"nodes.{i}.predicates.{j}.value", "code": "string_required"})
        elif node.kind == "time_bucket":
            if node.column not in allowed_columns:
                errors.append({"path": f"nodes.{i}.column", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            time_bucket_aliases.add(node.alias)
        elif node.kind == "aggregate":
            for j, group in enumerate(node.group_by):
                groupable_columns = allowed_columns | time_bucket_aliases
                if group.name not in groupable_columns:
                    errors.append({"path": f"nodes.{i}.group_by.{j}.name", "code": "unknown_column", "allowed": sorted(groupable_columns)})
            for j, m in enumerate(node.metrics):
                if m.column not in allowed_columns:
                    errors.append({"path": f"nodes.{i}.metrics.{j}.column", "code": "unknown_column", "allowed": sorted(allowed_columns)})
                aggregate_aliases.add(m.alias)
        elif node.kind == "window":
            window_inputs = allowed_columns | time_bucket_aliases | aggregate_aliases
            for j, metric in enumerate(node.metrics):
                if metric.column not in aggregate_aliases:
                    errors.append({"path": f"nodes.{i}.metrics.{j}.column", "code": "window_requires_aggregate", "allowed": sorted(aggregate_aliases)})
                for k, partition in enumerate(metric.partition_by):
                    if partition.name not in window_inputs:
                        errors.append({"path": f"nodes.{i}.metrics.{j}.partition_by.{k}.name", "code": "unknown_column", "allowed": sorted(window_inputs)})
                if metric.order_by.name not in window_inputs:
                    errors.append({"path": f"nodes.{i}.metrics.{j}.order_by.name", "code": "unknown_column", "allowed": sorted(window_inputs)})
                window_aliases.add(metric.alias)
        elif node.kind == "outlier":
            _check_unknown_columns(errors, f"nodes.{i}.value_column", [node.value_column], allowed_columns)
            for j, group in enumerate(node.group_by):
                if group.name not in allowed_columns:
                    errors.append({"path": f"nodes.{i}.group_by.{j}.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            analysis_aliases.add(node.z_score_alias)
        elif node.kind == "market_share":
            if node.group_by.name not in allowed_columns:
                errors.append({"path": f"nodes.{i}.group_by.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            _check_unknown_columns(errors, f"nodes.{i}.date_column", [node.date_column], allowed_columns)
            _check_unknown_columns(errors, f"nodes.{i}.revenue_column", [node.revenue_column], allowed_columns)
            analysis_aliases.update({node.start_alias, node.end_alias, node.change_alias})
        elif node.kind == "pareto":
            _check_unknown_columns(errors, f"nodes.{i}.value_column", [node.value_column], allowed_columns)
            analysis_aliases.update({node.count_alias, node.transaction_percentage_alias, node.revenue_percentage_alias})
        elif node.kind == "active_day_velocity":
            if node.group_by.name not in allowed_columns:
                errors.append({"path": f"nodes.{i}.group_by.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            _check_unknown_columns(errors, f"nodes.{i}.date_column", [node.date_column], allowed_columns)
            _check_unknown_columns(errors, f"nodes.{i}.revenue_column", [node.revenue_column], allowed_columns)
            analysis_aliases.update({node.total_alias, node.active_days_alias, node.velocity_alias})
        elif node.kind == "top_contributor":
            if node.outer_group_by.name not in allowed_columns:
                errors.append({"path": f"nodes.{i}.outer_group_by.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            if node.inner_group_by.name not in allowed_columns:
                errors.append({"path": f"nodes.{i}.inner_group_by.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            _check_unknown_columns(errors, f"nodes.{i}.value_column", [node.value_column], allowed_columns)
            if node.outer_group_by.name == node.inner_group_by.name:
                errors.append({"path": f"nodes.{i}.inner_group_by.name", "code": "outer_inner_must_differ"})
            if len({node.outer_value_alias, node.inner_value_alias, node.share_alias}) != 3:
                errors.append({"path": f"nodes.{i}", "code": "duplicate_alias"})
            analysis_aliases.update({node.outer_value_alias, node.inner_value_alias, node.share_alias})
        elif node.kind == "share_of_total":
            if node.group_by.name not in allowed_columns:
                errors.append({"path": f"nodes.{i}.group_by.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            _check_unknown_columns(errors, f"nodes.{i}.value_column", [node.value_column], allowed_columns)
            share_aliases = {
                node.total_alias, node.grand_total_alias, node.share_alias,
                node.projected_total_alias, node.projected_grand_total_alias, node.impact_alias,
            }
            if len(share_aliases) != 6:
                errors.append({"path": f"nodes.{i}", "code": "duplicate_alias"})
            analysis_aliases.update(share_aliases)
        elif node.kind == "group_deviation":
            if node.group_by.name not in allowed_columns:
                errors.append({"path": f"nodes.{i}.group_by.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            _check_unknown_columns(errors, f"nodes.{i}.value_column", [node.value_column], allowed_columns)
            deviation_aliases = {node.total_alias, node.mean_alias, node.z_score_alias, node.significance_alias}
            if len(deviation_aliases) != 4:
                errors.append({"path": f"nodes.{i}", "code": "duplicate_alias"})
            analysis_aliases.update(deviation_aliases)
        elif node.kind == "consistency":
            if node.group_by.name not in allowed_columns:
                errors.append({"path": f"nodes.{i}.group_by.name", "code": "unknown_column", "allowed": sorted(allowed_columns)})
            _check_unknown_columns(errors, f"nodes.{i}.date_column", [node.date_column], allowed_columns)
            _check_unknown_columns(errors, f"nodes.{i}.revenue_column", [node.revenue_column], allowed_columns)
            consistency_aliases = {
                node.total_alias, node.period_count_alias, node.avg_period_alias,
                node.stddev_period_alias, node.coefficient_of_variation_alias, node.consistency_score_alias,
            }
            if len(consistency_aliases) != 6:
                errors.append({"path": f"nodes.{i}", "code": "duplicate_alias"})
            analysis_aliases.update(consistency_aliases)
        elif node.kind == "sort":
            sortable_columns = allowed_columns | time_bucket_aliases | aggregate_aliases | window_aliases | analysis_aliases
            for j, key in enumerate(node.keys):
                if key.column not in sortable_columns:
                    errors.append({"path": f"nodes.{i}.keys.{j}.column", "code": "unknown_column", "allowed": sorted(sortable_columns)})

    if errors:
        raise ValidationError(errors)
