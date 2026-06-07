import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_security = HTTPBearer()


def _tokens_match(presented: str) -> bool:
    expected = settings.token
    if not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> None:
    if not _tokens_match(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
