"""启动后连接外键状态与异常连接丢弃。"""

import pytest
from app.db import _is_sqlite


@pytest.mark.skipif(not _is_sqlite, reason='SQLite连接PRAGMA恢复由SQLite CI组验证；PG并发由pg_gate验证')
@pytest.mark.parametrize('failure', [None, 'migration', 'commit'])
def test_init_db_restores_foreign_keys_on_same_pooled_connection(client, monkeypatch, failure, upgrade_legacy_schema):
    """Startup must never return the FK-disabled migration handle to the pool."""
    from sqlalchemy import event
    from app import db as database

    connections = [database.engine.connect(), database.engine.connect()]
    try:
        assert [conn.exec_driver_sql('PRAGMA foreign_keys').scalar() for conn in connections] == [1, 1]
    finally:
        for conn in connections:
            conn.close()
    checked_out = database.engine.pool.checkedout()
    trace = []

    def record_pragma(conn, cursor, statement, parameters, context, executemany):
        if statement.lower().replace(' ', '') in ('pragmaforeign_keys=off', 'pragmaforeign_keys=on'):
            trace.append((id(conn.connection.driver_connection), statement.lower().replace(' ', '')))

    from migrations import v243_data
    original_migrate = v243_data.migrate_legacy_data

    def migrate(db):
        original_migrate(db)
        if failure == 'migration':
            # Force an actual transaction before failure, not only SELECT/DDL.
            db.connection().exec_driver_sql("UPDATE users SET display_name='must roll back' WHERE username='admin'")
            raise RuntimeError('synthetic migration failure')
        if failure == 'commit':
            db.connection().exec_driver_sql("UPDATE users SET display_name='must roll back' WHERE username='admin'")
            fired = []
            def fail_commit(connection):
                if not fired:
                    fired.append(True)
                    raise RuntimeError('synthetic migration commit failure')
            event.listen(db.connection(), 'commit', fail_commit)

    monkeypatch.setattr(v243_data, 'migrate_legacy_data', migrate)
    # Replay only the frozen repair under test; later T20/T21/T22 DDL remains
    # applied, and the existing helper restores its actual recorded head.
    monkeypatch.setattr(database, '_alembic_sync_schema', upgrade_legacy_schema)
    event.listen(database.engine, 'before_cursor_execute', record_pragma)
    try:
        if failure:
            with pytest.raises(RuntimeError, match='synthetic migration'):
                database.init_db()
        else:
            database.init_db()
    finally:
        event.remove(database.engine, 'before_cursor_execute', record_pragma)
    assert database.engine.pool.checkedout() == checked_out
    off_handles = [handle for handle, statement in trace if statement.endswith('=off')]
    on_handles = [handle for handle, statement in trace if statement.endswith('=on')]
    # The bounded legacy replay performs upgrade + a separate head stamp on
    # success; failure exits before stamping. Each Alembic operation must
    # restore exactly the physical handle on which it disabled FK checks.
    assert len(off_handles) == (1 if failure else 2) and off_handles == on_handles, trace
    assert all(trace[index][0] == trace[index + 1][0] and trace[index][1].endswith('=off') and trace[index + 1][1].endswith('=on') for index in range(0, len(trace), 2)), trace
    connections = [database.engine.connect(), database.engine.connect()]
    try:
        assert [conn.exec_driver_sql('PRAGMA foreign_keys').scalar() for conn in connections] == [1, 1]
        assert connections[0].exec_driver_sql("SELECT display_name FROM users WHERE username='admin'").scalar() != 'must roll back'
    finally:
        for conn in connections:
            conn.close()
    assert database.engine.pool.checkedout() == checked_out


@pytest.mark.skipif(not _is_sqlite, reason='SQLite连接PRAGMA失效保护由SQLite CI组验证')
def test_init_db_discards_connection_if_foreign_key_restore_fails(client):
    from sqlalchemy import event
    from app import db as database

    handles = [database.engine.connect(), database.engine.connect()]
    for handle in handles:
        handle.close()
    checked_out = database.engine.pool.checkedout()
    disabled, invalidated = [], []

    def fail_restore(conn, cursor, statement, parameters, context, executemany):
        normalized = statement.lower().replace(' ', '')
        if normalized == 'pragmaforeign_keys=off':
            disabled.append(id(conn.connection.driver_connection))
        elif normalized == 'pragmaforeign_keys=on':
            raise RuntimeError('synthetic FK restore failure')

    def record_invalidation(dbapi_connection, connection_record, exception):
        invalidated.append(id(dbapi_connection))

    event.listen(database.engine, 'before_cursor_execute', fail_restore)
    event.listen(database.engine, 'invalidate', record_invalidation)
    try:
        with pytest.raises(RuntimeError, match='synthetic FK restore failure'):
            database.init_db()
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail_restore)
        event.remove(database.engine, 'invalidate', record_invalidation)
    assert disabled and disabled == invalidated
    assert database.engine.pool.checkedout() == checked_out
    handles = [database.engine.connect(), database.engine.connect()]
    try:
        assert [conn.exec_driver_sql('PRAGMA foreign_keys').scalar() for conn in handles] == [1, 1]
    finally:
        for handle in handles:
            handle.close()
    assert database.engine.pool.checkedout() == checked_out
