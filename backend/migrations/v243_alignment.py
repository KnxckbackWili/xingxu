"""Online alignment against the frozen 2.4.3 schema, never live application models."""
import copy
import sqlalchemy as sa
from migrations.v243_schema import metadata

LEGACY_REVISION = 'd2e7f9a103b4'


def _column(column, *, fill_default=False):
    default = column.server_default
    # Nullable additions retain unknown historical values (notably time_basis).
    if default is None and fill_default and not column.nullable and column.default is not None and column.default.is_scalar:
        value = column.default.arg
        default = sa.true() if value is True else sa.false() if value is False else str(value)
    return sa.Column(column.name, copy.copy(column.type), nullable=column.nullable,
                     primary_key=column.primary_key, server_default=default)


def align_schema(operations):
    """Preserve every row and unknown column; add all missing baseline objects."""
    if operations.get_context().as_sql:
        raise RuntimeError('2.4.3存量对齐需要在线核对，不能生成省略数据转换的离线SQL')
    bind = operations.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in metadata.sorted_tables:
        if table.name not in existing:
            operations.create_table(table.name,
                *[_column(c) for c in table.columns],
                *[copy.deepcopy(c) for c in table.constraints if not isinstance(c, sa.PrimaryKeyConstraint)])
            for index in sorted(table.indexes, key=lambda i: i.name):
                operations.create_index(index.name, table.name, [c.name for c in index.columns], unique=index.unique)
            continue
        columns = {c['name']: c for c in inspector.get_columns(table.name)}
        missing = [c for c in table.columns if c.name not in columns]
        temporary_defaults = []
        populated = bool(missing) and bind.execute(sa.select(sa.func.count()).select_from(table)).scalar() > 0
        for column in missing:
            added = _column(column, fill_default=True)
            if populated and not added.nullable and added.server_default is None:
                raise RuntimeError(f'2.4.3 alignment cannot invent {table.name}.{column.name}; restore a valid backup')
            operations.add_column(table.name, added)
            if column.server_default is None and added.server_default is not None:
                temporary_defaults.append(column.name)
        default_changes = [c.name for c in table.columns if c.name in columns and
                           columns[c.name].get('default') is not None and c.server_default is None]
        nullable_changes = [c.name for c in table.columns if c.name in columns and
                            columns[c.name]['nullable'] != c.nullable]
        existing_fk_keys = {(tuple(fk['constrained_columns']), fk['referred_table'],
                             tuple(fk['referred_columns']), fk.get('options', {}).get('ondelete'))
                            for fk in inspector.get_foreign_keys(table.name)}
        missing_fks = [fk for fk in table.foreign_key_constraints if
                       (tuple(fk.column_keys), fk.elements[0].column.table.name,
                        tuple(e.column.name for e in fk.elements), fk.ondelete) not in existing_fk_keys]
        unique_columns = {tuple(sorted(c['column_names'])) for c in inspector.get_unique_constraints(table.name)}
        missing_unique = [c for c in table.constraints if isinstance(c, sa.UniqueConstraint) and
                          tuple(sorted(c.columns.keys())) not in unique_columns]
        # These two old compatibility indexes duplicate model constraints. Leave
        # all unknown indexes and PostgreSQL constraint-owned indexes untouched.
        replacement_indexes = {'issues': 'uq_issue_project_client_uuid', 'tasks': 'ux_tasks_vehicle_event'}
        if table.name in replacement_indexes:
            existing_indexes = {i['name'] for i in inspector.get_indexes(table.name)
                                if not i.get('duplicates_constraint')}
            old_index = replacement_indexes[table.name]
            if old_index in existing_indexes:
                operations.drop_index(old_index, table_name=table.name)
        if temporary_defaults or default_changes or nullable_changes or missing_fks or missing_unique:
            with operations.batch_alter_table(table.name) as batch:
                for name in set(temporary_defaults + default_changes):
                    batch.alter_column(name, server_default=None, existing_type=table.c[name].type)
                for name in nullable_changes:
                    batch.alter_column(name, nullable=table.c[name].nullable, existing_type=table.c[name].type)
                for unique in missing_unique:
                    name = unique.name or 'uq_' + table.name + '_' + '_'.join(unique.columns.keys())
                    batch.create_unique_constraint(name, list(unique.columns.keys()))
                for fk in missing_fks:
                    first = fk.elements[0]
                    name = fk.name or f'fk_{table.name}_{first.parent.name}_{first.column.table.name}'
                    batch.create_foreign_key(name, first.column.table.name, list(fk.column_keys),
                                             [e.column.name for e in fk.elements], ondelete=fk.ondelete)
        inspector = sa.inspect(bind)
        indexes = {i['name'] for i in inspector.get_indexes(table.name)}
        for index in sorted(table.indexes, key=lambda i: i.name):
            if index.name not in indexes:
                operations.create_index(index.name, table.name, [c.name for c in index.columns], unique=index.unique)
