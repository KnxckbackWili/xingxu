"""Auth schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    # 浏览器会话走 HttpOnly Cookie（可空）；API 客户端走请求体
    refresh_token: Optional[str] = Field(default=None, min_length=1, max_length=4096)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    phone: str = ""
    email: str = ""
    is_active: bool = True

    model_config = {"from_attributes": True}


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


from pydantic import SecretStr, ConfigDict


class MfaChallengeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge: SecretStr


class MfaVerifyRequest(MfaChallengeRequest):
    otp: SecretStr = SecretStr('')
    recovery_code: SecretStr = SecretStr('')


class MfaProof(BaseModel):
    model_config = ConfigDict(extra='forbid')
    otp: SecretStr


class MfaPasswordProof(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: SecretStr


class MfaRecoveryProof(MfaPasswordProof):
    recovery_code: SecretStr
