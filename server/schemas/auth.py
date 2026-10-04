from pydantic import BaseModel


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    two_factor_enabled: bool = False


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResult(BaseModel):
    """The final result of a completed signup/login - the user's identity plus
    the session token the client must send as `Authorization: Bearer <token>`
    on every subsequent request (see server/api/dependencies.py). Only returned
    from POST /auth/verify-code, once the emailed code has been confirmed."""

    id: int
    name: str
    email: str
    token: str


class PendingVerificationResult(BaseModel):
    """Signup/login response before 2FA - no session token yet. The client
    holds `pending_token` and submits it with the emailed code to
    POST /auth/verify-code to get a real AuthResult."""

    pending_token: str
    email: str


class VerifyCodeRequest(BaseModel):
    pending_token: str
    code: str


class ResendCodeRequest(BaseModel):
    pending_token: str
