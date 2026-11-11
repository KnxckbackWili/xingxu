"""Who may call a route: any signed-in account, administrators only, or (marked) nobody's session.

Every /api route must depend on get_current_user or require_admin, or carry @public with a reason.
The application refuses to start when a route declares none of them.
"""
from fastapi.routing import APIRoute


def public(reason: str):
    def mark(function):
        function.__public_reason__ = reason
        return function
    return mark


def api_routes(app):
    """Every declared route with its full path. FastAPI includes routers lazily, so app.routes
    alone lists almost none of them."""
    from fastapi.routing import _iter_routes_with_context
    for original, context in _iter_routes_with_context(app.routes):
        route = context or original
        if isinstance(original, APIRoute) and route.path.startswith("/api"):
            yield route


def _dependencies(dependant):
    for child in dependant.dependencies:
        yield child.call
        yield from _dependencies(child)


def route_access(route) -> str:
    """'public', 'admin' or 'account' for a declared route; '' when it declares nothing."""
    from app.deps import get_current_user, require_admin
    if getattr(route.endpoint, "__public_reason__", ""):
        return "public"
    calls = set(_dependencies(route.dependant))
    if require_admin in calls:
        return "admin"
    return "account" if get_current_user in calls else ""


def validate_routes(app) -> None:
    missing = [f"{sorted(route.methods)} {route.path}" for route in api_routes(app) if not route_access(route)]
    if missing:
        raise RuntimeError("以下接口没有声明谁可以调用：" + "；".join(missing))
