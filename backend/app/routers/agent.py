"""HTTP bridge for agents without an MCP client; shares the MCP tool registry."""
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.system_permissions import route_permission_contextual
from app.services.agent_auth import authenticate_agent
from app.services.ai_mcp import TOOL_SCOPES, _mcp_scopes, _mcp_user_id, mcp

router = APIRouter(prefix="/agent", tags=["Agent 接口"])
bearer = HTTPBearer(auto_error=False)


async def agent_identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    value = f"{credentials.scheme} {credentials.credentials}" if credentials else ""
    user_id, scopes = await run_in_threadpool(authenticate_agent, value)
    from app.services.ai_mcp import _mcp_token_id
    api_token = _mcp_token_id.set(getattr(scopes, "token_id", None))
    user_token, scope_token = _mcp_user_id.set(user_id), _mcp_scopes.set(scopes)
    try:
        yield scopes
    finally:
        _mcp_user_id.reset(user_token)
        _mcp_scopes.reset(scope_token)
        _mcp_token_id.reset(api_token)


class ToolCall(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools")
@route_permission_contextual('system.agent.use', reason='专用令牌认证及工具逐次scope和资源权限校验')
async def list_agent_tools(scopes: list[str] = Depends(agent_identity)):
    """Return only scope-authorized tools and their JSON input schemas."""
    return {"protocol": "agv-agent-v1", "mcp_path": "/api/ai/mcp/", "tools": [
        {**tool.model_dump(by_alias=True, exclude_none=True), "required_scopes": TOOL_SCOPES[tool.name]}
        for tool in await mcp.list_tools() if set(TOOL_SCOPES[tool.name]).issubset(scopes)
    ]}


@router.post("/tools/{name}")
@route_permission_contextual('system.agent.use', reason='专用令牌认证及工具逐次scope和资源权限校验')
async def call_agent_tool(name: str, body: ToolCall, scopes: list[str] = Depends(agent_identity)):
    if name not in TOOL_SCOPES:
        raise HTTPException(404, "工具不存在")
    if not set(TOOL_SCOPES[name]).issubset(scopes):
        raise HTTPException(403, "Token 未授权此工具所需权限")
    try:
        content = await mcp.call_tool(name, body.arguments)
    except ToolError:
        raise HTTPException(422, "工具参数无效，请按工具目录中的 inputSchema 传参") from None
    # Registered tools return one JSON text envelope; no arbitrary external tool execution.
    return json.loads(content[0].text)
