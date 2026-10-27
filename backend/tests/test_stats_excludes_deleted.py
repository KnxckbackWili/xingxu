"""Recycled projects are absent from current statistics and personnel weeks.

The former mixed-unit workload endpoint is retired, while the original visibility
invariant remains enforced against current factual projections.
"""
from tests.test_vehicle_progress import setup_fleet


def remove(client,headers,pid):
    current=client.get('/api/projects/'+pid,headers=headers).json()
    response=client.delete('/api/projects/'+pid,headers=headers,params={'version':current['version']})
    assert response.status_code==200,response.text


def test_stats_excludes_soft_deleted_project(client,pm_headers):
    pid,_=setup_fleet(client,pm_headers,2)
    before=client.get('/api/dashboard/statistics',headers=pm_headers)
    assert before.status_code==200 and before.json()['projects']==1
    assert before.json()['vehicle_progress']['target']==10
    assert any(row['id']==pid for row in client.get('/api/projects',headers=pm_headers).json())
    remove(client,pm_headers,pid)
    after=client.get('/api/dashboard/statistics',headers=pm_headers).json()
    assert after['projects']==0 and after['vehicle_progress']['target']==0
    assert not client.get('/api/projects',headers=pm_headers).json()


def test_dashboard_overview_excludes_soft_deleted_project(client,pm_headers):
    pid,_=setup_fleet(client,pm_headers,1)
    assert any(row['id']==pid for row in client.get('/api/dashboard/overview',headers=pm_headers).json()['projects'])
    remove(client,pm_headers,pid)
    assert not client.get('/api/dashboard/overview',headers=pm_headers).json()['projects']


def test_global_workload_excludes_soft_deleted_project(client,pm_headers):
    pid,_=setup_fleet(client,pm_headers,1)
    assert client.get('/api/dashboard/workload',headers=pm_headers).status_code==410
    before=client.get('/api/people/weeks',headers=pm_headers)
    assert before.status_code==200 and any(p['id']==pid for p in before.json()['projects'])
    remove(client,pm_headers,pid)
    assert not client.get('/api/people/weeks',headers=pm_headers).json()['projects']
    assert client.get('/api/dashboard/statistics',headers=pm_headers).json()['projects']==0
