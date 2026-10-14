"""add mps core tables

Revision ID: 62ad14d88051
Revises: b2c3d4e5f6g7
Create Date: 2026-10-14 15:12:08.941709

"""
import sqlalchemy as sa

from alembic import op

revision = "62ad14d88051"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def _sync_cols() -> list[sa.Column]:
    """SyncBase 出箱列（与 app/models/base.py 一致）。"""
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hap_row_id", sa.String(64), nullable=True),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="SYNCED"),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def _sync_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_hap_row_id", table, ["hap_row_id"])
    op.create_index(f"ix_{table}_sync_status", table, ["sync_status"])


TABLES = [
    "process_masters", "process_sets", "process_routes", "orders", "order_operations",
    "system_params", "schedule_batches", "schedule_allocations",
    "priority_logs", "priority_batches",
    "hap_connections", "hap_mappings", "hap_field_mappings",
]


def upgrade() -> None:
    op.create_table(
        "process_masters",
        *_sync_cols(),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("op", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("cycle", sa.Float(), nullable=False),
        sa.Column("yield_assembly", sa.Float(), nullable=True),
        sa.Column("yield_inspect", sa.Float(), nullable=True),
        sa.Column("yield_overall", sa.Float(), nullable=True),
        sa.Column("cap_station", sa.Float(), nullable=True),
        sa.Column("stations", sa.Integer(), nullable=True),
        sa.Column("flux_base", sa.Float(), nullable=True),
        sa.Column("flux_peak", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(100), nullable=True),
        sa.Column("feature", sa.String(50), nullable=True),
        sa.Column("split_rule", sa.String(50), nullable=True),
        sa.Column("split_threshold", sa.Integer(), nullable=True),
        sa.Column("cycle_note", sa.String(100), nullable=True),
        sa.Column("remark", sa.String(200), nullable=True),
        sa.UniqueConstraint("level", "op", "mode", name="uq_process_master"),
    )
    _sync_indexes("process_masters")

    op.create_table(
        "process_sets",
        *_sync_cols(),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("form", sa.String(50), nullable=True),
        sa.Column("arch", sa.String(50), nullable=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("feature", sa.String(100), nullable=True),
        sa.Column("version", sa.String(20), nullable=True),
        sa.Column("route_text", sa.String(200), nullable=True),
        sa.Column("owner", sa.String(50), nullable=True),
        sa.Column("yield_ref", sa.Float(), nullable=True),
        sa.Column("ratio_ref", sa.Float(), nullable=True),
        sa.Column("cycle_ref", sa.Float(), nullable=True),
        sa.Column("urgent_ref", sa.Float(), nullable=True),
        sa.Column("required_flags", sa.JSON(), nullable=True),
        sa.Column("subpart_mode", sa.String(10), nullable=True),
        sa.Column("subpart_cycle", sa.Float(), nullable=True),
        sa.Column("ramp_days", sa.Integer(), nullable=True),
        sa.Column("bottleneck_op", sa.String(50), nullable=True),
        sa.Column("bottleneck_flux", sa.Float(), nullable=True),
        sa.Column("water_note", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("remark", sa.String(200), nullable=True),
    )
    _sync_indexes("process_sets")

    op.create_table(
        "process_routes",
        *_sync_cols(),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step_raw", sa.String(50), nullable=False),
        sa.Column("step_std", sa.String(50), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("cycle", sa.Float(), nullable=True),
        sa.Column("yield_inspect", sa.Float(), nullable=True),
        sa.Column("yield_overall", sa.Float(), nullable=True),
        sa.Column("feature", sa.String(100), nullable=True),
        sa.Column("cf_field", sa.String(50), nullable=True),
        sa.Column("cf_trigger", sa.String(100), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.UniqueConstraint("code", "seq", name="uq_route_code_seq"),
    )
    _sync_indexes("process_routes")

    op.create_table(
        "orders",
        *_sync_cols(),
        sa.Column("order_no", sa.String(50), nullable=False, unique=True),
        sa.Column("product", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("first_flag", sa.String(20), nullable=False),
        sa.Column("water_vapor", sa.String(10), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("kit_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("remark", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("prio_level", sa.String(5), nullable=True),
        sa.Column("prio_score", sa.Float(), nullable=True),
        sa.Column("prio_source", sa.String(10), nullable=True),
        sa.Column("prio_manual", sa.Integer(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("pinned_until", sa.Date(), nullable=True),
        sa.Column("pinned_at", sa.DateTime(), nullable=True),
        sa.Column("pinned_by", sa.String(50), nullable=True),
        sa.Column("sort_no", sa.Float(), nullable=True),
        sa.Column("prio_updated_at", sa.DateTime(), nullable=True),
        sa.Column("prio_updated_by", sa.String(50), nullable=True),
        sa.Column("input_qty", sa.Integer(), nullable=True),
        sa.Column("yield_ratio", sa.Float(), nullable=True),
        sa.Column("y_full", sa.Float(), nullable=True),
        sa.Column("cycle_single", sa.Float(), nullable=True),
        sa.Column("cycle_batch", sa.Float(), nullable=True),
        sa.Column("adopted_flux", sa.Float(), nullable=True),
        sa.Column("bottleneck_op", sa.String(50), nullable=True),
        sa.Column("ramp_applied", sa.Integer(), nullable=True),
        sa.Column("delivery_cycle", sa.Float(), nullable=True),
        sa.Column("latest_start_date", sa.Date(), nullable=True),
        sa.Column("plan_start_date", sa.Date(), nullable=True),
        sa.Column("plan_finish_date", sa.Date(), nullable=True),
        sa.Column("gap_days", sa.Integer(), nullable=True),
        sa.Column("judge", sa.String(20), nullable=True),
        sa.Column("strategy_id", sa.String(50), nullable=True),
    )
    _sync_indexes("orders")

    op.create_table(
        "order_operations",
        *_sync_cols(),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("op", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(20), nullable=True),
        sa.Column("qty", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("feature_key", sa.String(20), nullable=True),
        sa.Column("feature_usage", sa.Float(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("depends_on_id", sa.String(36), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
    )
    _sync_indexes("order_operations")
    op.create_index("ix_order_operations_order_id", "order_operations", ["order_id"])

    op.create_table(
        "system_params",
        *_sync_cols(),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("group_name", sa.String(50), nullable=True),
        sa.Column("hint", sa.String(200), nullable=True),
    )
    _sync_indexes("system_params")

    op.create_table(
        "schedule_batches",
        *_sync_cols(),
        sa.Column("batch_no", sa.String(50), nullable=False, unique=True),
        sa.Column("base_date", sa.Date(), nullable=True),
        sa.Column("solver_mode", sa.String(20), nullable=True),
        sa.Column("strategy_id", sa.String(50), nullable=True),
        sa.Column("params_snapshot", sa.JSON(), nullable=True),
        sa.Column("kpi", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
    )
    _sync_indexes("schedule_batches")

    op.create_table(
        "schedule_allocations",
        *_sync_cols(),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=True),
        sa.Column("resource_key", sa.String(100), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
    )
    _sync_indexes("schedule_allocations")
    op.create_index("ix_schedule_allocations_batch_id", "schedule_allocations", ["batch_id"])

    op.create_table(
        "priority_logs",
        *_sync_cols(),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("order_no", sa.String(50), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("old_priority", sa.Integer(), nullable=True),
        sa.Column("new_priority", sa.Integer(), nullable=True),
        sa.Column("old_level", sa.String(5), nullable=True),
        sa.Column("new_level", sa.String(5), nullable=True),
        sa.Column("old_sort_no", sa.Float(), nullable=True),
        sa.Column("new_sort_no", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("operator", sa.String(50), nullable=True),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("undo_of", sa.String(36), nullable=True),
    )
    _sync_indexes("priority_logs")
    op.create_index("ix_priority_logs_order_id", "priority_logs", ["order_id"])

    op.create_table(
        "priority_batches",
        *_sync_cols(),
        sa.Column("batch_id", sa.String(36), nullable=False, unique=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("operator", sa.String(50), nullable=True),
        sa.Column("undone", sa.Boolean(), nullable=False),
    )
    _sync_indexes("priority_batches")

    op.create_table(
        "hap_connections",
        *_sync_cols(),
        sa.Column("base_url", sa.String(200), nullable=True),
        sa.Column("app_id", sa.String(100), nullable=True),
        sa.Column("app_key_enc", sa.Text(), nullable=True),
        sa.Column("sign_enc", sa.Text(), nullable=True),
    )
    _sync_indexes("hap_connections")

    op.create_table(
        "hap_mappings",
        *_sync_cols(),
        sa.Column("entity", sa.String(50), nullable=False, unique=True),
        sa.Column("ws_id", sa.String(64), nullable=True),
        sa.Column("sync_direction", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    _sync_indexes("hap_mappings")

    op.create_table(
        "hap_field_mappings",
        *_sync_cols(),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("local_field", sa.String(50), nullable=False),
        sa.Column("hap_field_id", sa.String(64), nullable=True),
        sa.Column("hap_field_name", sa.String(100), nullable=True),
        sa.Column("field_type", sa.String(20), nullable=True),
        sa.Column("option_map", sa.JSON(), nullable=True),
        sa.Column("relation", sa.JSON(), nullable=True),
        sa.Column("auto_score", sa.Float(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("entity", "local_field", name="uq_hap_field_mapping"),
    )
    _sync_indexes("hap_field_mappings")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
