"""Local Docker-exec bridge. This is not an HTTP endpoint or a listening daemon."""
import json
import sys

# This side process can run while web/scheduler still own the database. It must
# never consume an operator's pending restore merely to publish a heartbeat.
if __name__ == "__main__":
    sys._xingxu_host_update_bridge = True



def dispatch(request):
    from app.services import system_updates as updates
    action = request.get("action")
    runner_id = request.get("runner_id")
    if action == "heartbeat":
        return updates.heartbeat(runner_id, request.get("protocol"), request.get("trust_protocol"), request.get("trust_configured"))
    if action == "trust-request":
        return updates.trust_request(runner_id)
    if action == "trust-credentials":
        return updates.trust_credentials(runner_id, request.get("check_id"), request.get("job_id"))
    if action == "trust-result":
        return updates.trust_result(runner_id, request.get("check_id"), request.get("status"), request.get("method"), request.get("reason"))
    if action == "claim":
        return updates.claim(runner_id)
    if action == "prepare":
        return updates.prepare(runner_id, request.get("job_id"))
    if action == "report":
        # Do not publish raw tool output supplied in phase/message fields.
        return updates.report(runner_id, request.get("job_id"), request.get("status"), request.get("reason"))
    raise updates.UpdateError("更新服务操作无效")


def main():
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError()
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError()
        result = dispatch(request)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        # Never expose remote HTTP bodies, tokens, filesystem contents or env.
        print(json.dumps({"error": "更新服务操作失败，请检查任务状态与本机日志"}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
