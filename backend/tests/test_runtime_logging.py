"""Schema startup must not hide errors from the running ASGI server."""
import logging


def test_schema_initialization_preserves_server_error_logging(client):
    from app.db import init_db
    logger = logging.getLogger('uvicorn.error')
    logger.disabled = False
    init_db()
    assert logger.disabled is False, 'Migration logging disabled the server exception log'
