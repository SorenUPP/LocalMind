from typing import Annotated, Literal
from pydantic import BaseModel, Field

ScalarValue = str | float | int | bool
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]

class ColumnRef(BaseModel):
    name: str

class Predicate(BaseModel):
    column: str
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains", "in"]
    value: ScalarValue | list[ScalarValue]

class AggregateMetric(BaseModel):
    column: str
    fn: Literal["sum", "mean", "count", "min", "max", "stddev"]
    alias: Identifier

class SortKey(BaseModel):
    column: str
    direction: Literal["asc", "desc"] = "asc"

class FilterNode(BaseModel):
    kind: Literal["filter"]
    predicates: list[Predicate]

class AggregateNode(BaseModel):
    kind: Literal["aggregate"]
    group_by: list[ColumnRef]
    metrics: list[AggregateMetric]


class TimeBucketNode(BaseModel):
    kind: Literal["time_bucket"]
    column: str
    granularity: Literal["month"]
    alias: Identifier


class WindowMetric(BaseModel):
    column: Identifier
    fn: Literal["pct_change"]
    alias: Identifier
    partition_by: list[ColumnRef]
    order_by: ColumnRef


class WindowNode(BaseModel):
    kind: Literal["window"]
    metrics: list[WindowMetric]


class OutlierNode(BaseModel):
    kind: Literal["outlier"]
    value_column: str
    group_by: list[ColumnRef]
    threshold: float = Field(default=2, gt=0)
    z_score_alias: Identifier = "z_score"


class MarketShareNode(BaseModel):
    kind: Literal["market_share"]
    group_by: ColumnRef
    date_column: str
    revenue_column: str
    start_date: str
    end_date: str
    start_alias: Identifier = "start_market_share"
    end_alias: Identifier = "end_market_share"
    change_alias: Identifier = "market_share_change"


class ParetoNode(BaseModel):
    kind: Literal["pareto"]
    value_column: str
    threshold_percent: float = Field(default=50, gt=0, le=100)
    count_alias: Identifier = "top_transaction_count"
    transaction_percentage_alias: Identifier = "top_transaction_percentage"
    revenue_percentage_alias: Identifier = "cumulative_revenue_percentage"


class ActiveDayVelocityNode(BaseModel):
    kind: Literal["active_day_velocity"]
    group_by: ColumnRef
    date_column: str
    revenue_column: str
    total_alias: Identifier = "total_revenue"
    active_days_alias: Identifier = "active_selling_days"
    velocity_alias: Identifier = "revenue_per_active_day"


class TopContributorNode(BaseModel):
    kind: Literal["top_contributor"]
    outer_group_by: ColumnRef
    inner_group_by: ColumnRef
    value_column: str
    outer_value_alias: Identifier = "outer_total"
    inner_value_alias: Identifier = "inner_total"
    share_alias: Identifier = "revenue_share"


class ShareOfTotalNode(BaseModel):
    kind: Literal["share_of_total"]
    group_by: ColumnRef
    value_column: str
    change_percent: float | None = Field(default=None, ge=-100, le=1000)
    total_alias: Identifier = "group_total"
    grand_total_alias: Identifier = "grand_total"
    share_alias: Identifier = "share_of_total_percent"
    projected_total_alias: Identifier = "projected_group_total"
    projected_grand_total_alias: Identifier = "projected_grand_total"
    impact_alias: Identifier = "impact_on_grand_total_percent"


class GroupDeviationNode(BaseModel):
    kind: Literal["group_deviation"]
    group_by: ColumnRef
    value_column: str
    threshold: float = Field(default=1, gt=0)
    total_alias: Identifier = "group_total"
    mean_alias: Identifier = "group_mean"
    z_score_alias: Identifier = "deviation_z_score"
    significance_alias: Identifier = "significance"


class ConsistencyNode(BaseModel):
    kind: Literal["consistency"]
    group_by: ColumnRef
    date_column: str
    revenue_column: str
    granularity: Literal["day", "month"] = "month"
    total_alias: Identifier = "total_revenue"
    period_count_alias: Identifier = "period_count"
    avg_period_alias: Identifier = "avg_period_revenue"
    stddev_period_alias: Identifier = "stddev_period_revenue"
    coefficient_of_variation_alias: Identifier = "coefficient_of_variation"
    consistency_score_alias: Identifier = "consistency_score"


class SortNode(BaseModel):
    kind: Literal["sort"]
    keys: list[SortKey]

class LimitNode(BaseModel):
    kind: Literal["limit"]
    count: int = Field(ge=1, le=10000)

DiscriminatedNode = Annotated[
    FilterNode | TimeBucketNode | AggregateNode | WindowNode | OutlierNode | MarketShareNode | ParetoNode
    | ActiveDayVelocityNode | TopContributorNode | ShareOfTotalNode | GroupDeviationNode | ConsistencyNode
    | SortNode | LimitNode,
    Field(discriminator="kind"),
]

class QueryPlan(BaseModel):
    dataset: str
    nodes: list[DiscriminatedNode]
