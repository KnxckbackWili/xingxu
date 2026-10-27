"""Notification filters apply before pagination without changing ownership scope."""
from datetime import datetime


def test_type_filter_before_pagination_with_stable_order(client, admin_headers):
    from app.db import SessionLocal
    from app.models import User, Notification
    with SessionLocal() as db:
        admin = db.query(User).filter(User.username == 'admin').one()
        other = db.query(User).filter(User.username == 'worker1').one()
        # Equal timestamps intentionally verify the deterministic id tie-breaker.
        for i in range(25):
            db.add(Notification(id=f'noise-{i:02}', user_id=admin.id, title='系统', content='', ntype='system', created_at=datetime(2026, 9, 30)))
        for i in range(3):
            db.add(Notification(id=f'report-{i}', user_id=admin.id, title='报告', content='', ntype='report', is_read=i == 2, created_at=datetime(2026, 9, 30)))
        db.add(Notification(id='foreign-report', user_id=other.id, title='私有', content='', ntype='report'))
        db.commit()
    first = client.get('/api/notifications?ntype=report&limit=2', headers=admin_headers).json()
    second = client.get('/api/notifications?ntype=report&limit=2&offset=2', headers=admin_headers).json()
    assert [n['id'] for n in first + second] == ['report-2', 'report-1', 'report-0']
    unread = client.get('/api/notifications?ntype=report&unread_only=true', headers=admin_headers).json()
    assert [n['id'] for n in unread] == ['report-1', 'report-0']
    unfiltered = client.get('/api/notifications?limit=50', headers=admin_headers).json()
    assert len(unfiltered) == 28
    assert client.get('/api/notifications?ntype=unknown', headers=admin_headers).json() == []
