"""Local teaching-only shared secret; never a user/owner selector."""
import secrets

from fastapi import HTTPException, Request


async def require_admin(request: Request):
    expected = request.app.state.admin_password
    if expected is None:
        raise HTTPException(503, "Writing is disabled.")
    values = request.headers.getlist("authorization")
    value = values[0] if len(values) == 1 else ""
    scheme, _, supplied = value.partition(" ")
    if scheme.lower() != "bearer" or not supplied or not secrets.compare_digest(
        supplied.encode("utf-8"), expected
    ):
        raise HTTPException(401, "Unauthorized.", headers={"WWW-Authenticate": "Bearer"})
