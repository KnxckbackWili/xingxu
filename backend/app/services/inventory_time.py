"""Timestamp provenance for inventory histories without rewriting legacy data."""

SERVER_TIME_NOTES = {
    "建立台账时的初始数量", "批量导入时的初始数量",
    "编辑台账时调整数量", "导入项目时的初始数量",
}

def resolve_inventory_time_basis(time_basis, movement_type, note):
    if time_basis in {"utc", "legacy_local"}:
        return time_basis
    # Only exact server-generated initial/adjustment records are provably UTC.
    if movement_type in {"inventory", "adjust"} and note in SERVER_TIME_NOTES:
        return "utc"
    return "legacy_local"


def inventory_time_basis(row):
    return resolve_inventory_time_basis(row.time_basis, row.movement_type, row.note)
