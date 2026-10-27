#!/usr/bin/env bash
# AGV-PM 部署验证脚本：构建镜像 → 启动容器 → 走通核心业务流程
# 用法: bash docker/scripts/verify.sh
# 代理/网络异常时可用 DOCKER_BUILD_NETWORK=host 让构建容器使用宿主机网络。
set -euo pipefail

IMAGE=agv-pm:verify
CONTAINER=agv-pm-verify
PORT=8090
BUILD_NETWORK="${DOCKER_BUILD_NETWORK:-default}"

cleanup() {
  docker rm -f "$CONTAINER" > /dev/null 2>&1 || true
  docker rmi "$IMAGE" > /dev/null 2>&1 || true
}
trap cleanup EXIT

echo "▸ 1/9 构建镜像（约 5-10 分钟）"
docker build --network "$BUILD_NETWORK" -f docker/Dockerfile -t "$IMAGE" .

echo "▸ 2/9 启动容器"
docker rm -f "$CONTAINER" 2>/dev/null || true
docker run -d --name "$CONTAINER" -p "$PORT:8000" \
  -e SECRET_KEY="verify-only-secret-key" \
  -e SEED_DEMO_USERS=1 \
  -e TZ=Asia/Shanghai \
  "$IMAGE" > /dev/null

echo "▸ 3/9 等待服务就绪"
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
    echo "   ✓ 服务就绪（${i}s）"
    break
  fi
  [ "$i" = 60 ] && { echo "   ✗ 服务未就绪"; exit 1; }
  sleep 1
done

echo "▸ 4/9 登录 + 创建项目 + 车型"
TOKEN=$(curl -sf -X POST "http://127.0.0.1:$PORT/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
PID=$(curl -sf -X POST "http://127.0.0.1:$PORT/api/projects" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"验证项目","start_date":"2026-08-10","end_date":"2026-09-30"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sf -X POST "http://127.0.0.1:$PORT/api/projects/$PID/vehicles" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"vehicle_type":"潜伏式","model_name":"AGV-500","quantity":2}' > /dev/null
echo "   ✓ 项目创建成功: $PID"

echo "▸ 5/9 生成任务 + 自动排程"
curl -sf -X POST "http://127.0.0.1:$PORT/api/projects/$PID/tasks/generate" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"module_ids":["mod-01","mod-02","mod-03","mod-04","mod-05","mod-06","mod-07","mod-08"]}' \
  | python3 -c "import sys,json;print('   ✓', json.load(sys.stdin)['message'])"
curl -sf -X POST "http://127.0.0.1:$PORT/api/projects/$PID/schedule/generate" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"   ✓ 日程 {d['entries']} 条 / {d['total_hours']} 小时\")"

echo "▸ 6/9 消息中心 + 看板移动 + 报告（v1.1 烟测）"
curl -sf "http://127.0.0.1:$PORT/api/notifications?limit=1&offset=0" \
  -H "Authorization: Bearer $TOKEN" -o /dev/null
echo "   ✓ 通知分页（offset）可用"
MOVE=$(curl -sf "http://127.0.0.1:$PORT/api/projects/$PID/tree" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
task = d[0]['modules'][0]['tasks'][0]
target = d[1]['id']
print(f\"{task['id']} {target}\")
")
TASK_ID=$(echo "$MOVE" | cut -d' ' -f1)
PHASE2=$(echo "$MOVE" | cut -d' ' -f2)
curl -sf -X PUT "http://127.0.0.1:$PORT/api/projects/$PID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"phase_id\":\"$PHASE2\"}" -o /dev/null
echo "   ✓ 任务跨阶段移动成功"
# 报告端点（定时报告的数据源）
curl -sf "http://127.0.0.1:$PORT/api/projects/$PID/report?period=week" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);assert 'summary' in d and 'progress' in d;print('   ✓ 周报生成:', d['period_label'])"
# 甘特拖拽等价：整任务平移 1 天
SHIFT=$(curl -sf "http://127.0.0.1:$PORT/api/projects/$PID/schedule" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
e = d[0]
print(f\"{e['id']} {e['work_date']}\")
")
EID=$(echo "$SHIFT" | cut -d' ' -f1)
EDATE=$(echo "$SHIFT" | cut -d' ' -f2)
NEWDATE=$(python3 -c "from datetime import date,timedelta;print((date.fromisoformat('$EDATE')+timedelta(days=1)).isoformat())")
curl -sf -X PUT "http://127.0.0.1:$PORT/api/schedule/$EID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"work_date\":\"$NEWDATE\"}" -o /dev/null
echo "   ✓ 日程平移: $EDATE -> $NEWDATE"
# 附件挂载实体（v1.2）：问题附件 + 交付物更新
# 用独立占位图片（不依赖第 7 步才生成的导出文件，避免干净环境 curl -f 失败中断）
printf '\x89PNG\r\n\x1a\nplaceholder' > /tmp/agvpm-issue-photo.png
ISSUE_ID=$(curl -sf -X POST "http://127.0.0.1:$PORT/api/projects/$PID/issues" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"烟测问题附件","severity":"low"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sf -X POST "http://127.0.0.1:$PORT/api/projects/$PID/attachments" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/agvpm-issue-photo.png" -F "entity_type=issue" -F "entity_id=$ISSUE_ID" -o /dev/null
curl -sf "http://127.0.0.1:$PORT/api/projects/$PID/attachments?entity_type=issue&entity_id=$ISSUE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;assert len(json.load(sys.stdin))==1;print('   ✓ 问题附件挂载: entity 过滤命中')"
curl -sf -X POST "http://127.0.0.1:$PORT/api/projects/$PID/tasks/$TASK_ID/deliverables" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"deliverables":[{"name":"验收单","done":true,"attachment_id":null}]}' -o /dev/null
echo "   ✓ 交付物更新（成员权限）可用"

echo "▸ 7/9 导出烟测（Excel 15 sheet 含原 13 + 模板 JSON）"
curl -sf "http://127.0.0.1:$PORT/api/projects/$PID/export/excel" \
  -H "Authorization: Bearer $TOKEN" -o /tmp/agvpm-export.xlsx
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/verify_excel.py" /tmp/agvpm-export.xlsx
curl -sf "http://127.0.0.1:$PORT/api/templates/export/json" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('   ✓ 模板 JSON 导出:', len(d['phases']), '阶段')"
TPL_TREE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/templates/tree" \
  -H "Authorization: Bearer $TOKEN")
[ "$TPL_TREE" = "200" ] || { echo "   ✗ 模板树 /templates/tree 返回 $TPL_TREE"; exit 1; }
echo "   ✓ 模板树 /templates/tree: $TPL_TREE"

echo "▸ 8/9 前端资源 + PWA"
SPA=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/")
SW=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/sw.js")
[ "$SPA" = "200" ] || { echo "   ✗ SPA 返回 $SPA（应为 200）"; exit 1; }
[ "$SW" = "200" ] || { echo "   ✗ Service Worker 返回 $SW（应为 200）"; exit 1; }
echo "   ✓ SPA: $SPA  ·  Service Worker: $SW"

echo "▸ 9/9 清理"
cleanup
trap - EXIT

echo ""
echo "✅ 全部验证通过！镜像可部署到 NAS。"
echo "部署方法见 docs/deployment.md"
