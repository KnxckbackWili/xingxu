"""历史统计分组、人员候选池及 AI 状态读取权限。"""


def test_ai_status_is_readable_by_all_authenticated_roles(client, admin_headers, pm_headers, worker_headers, tech_headers, lead_headers):
    """T021：/ai-projects/status 对非 admin/pm 角色也应 200（不误显示为未配置）。

    director/lead/technician/worker 拿到 403 会被前端 /pm/ai 误判为「AI 未配置」。
    """
    for headers in (admin_headers, pm_headers, worker_headers, tech_headers, lead_headers):
        r = client.get('/api/ai-projects/status', headers=headers)
        assert r.status_code == 200, r.status_code
        assert 'available' in r.json() and 'providers' in r.json()
