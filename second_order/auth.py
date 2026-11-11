"""Who is asking, and what each route lets them do (docs/admin-user-contract.md, user-api-0.3 and admin-api-0.2,
docs/onboarding-contract.md and docs/account-binding-contract.md).

Two modes. A server built with an accounts store (every ``serve``) is in ``accounts`` mode: the session cookie names a
server-side session, the role comes from the store, and every route is admin-only unless it is listed here as public
(the session routes, the public credit terms and registration) or user (``/api/user/*``); the client build and its
public pages are served to anyone, the admin build only to admins. A server built in code without an accounts store
(unit tests of the existing operator routes, the existing browser checks' launcher) is in ``local-operator`` mode: every
request is the local operator with the admin role, exactly as the server behaved before accounts existed. No
command-line option selects it.

The local Host check (api.check_local_host) runs before this, and every write still needs this server's Origin and its
route's custom header (api.check_local_write).

Account binding (docs/account-binding-contract.md): a page names the account it was opened for in ACCOUNT_HEADER. A
browser keeps one session cookie for all its tabs, so after a sign-in elsewhere an older tab's request carries another
account's cookie; the binding is how the server tells. Wherever the header is sent it must name the session's account,
or the request is refused before any route runs (401 account_changed: nothing read, nothing written). A user or
administrator write must send it (428 account_binding_required). Sign-in, registration and the session read ignore it;
signing out checks it when it is sent, and does not require it, since ending a session writes nothing to any account.
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from .accounts import Identity

USER_CONTRACT = "user-api-0.5"
ONBOARDING_CONTRACT = "onboarding-api-0.1"
ADMIN_CONTRACT = "admin-api-0.4"
SESSION_COOKIE = "second_order_session"
SESSION_HEADER = "x-second-order-session"
USER_HEADER = "x-second-order-user"
ADMIN_HEADER = "x-second-order-admin"
ACCOUNT_HEADER = "x-second-order-account"
READ_METHODS = ("GET", "HEAD", "OPTIONS")
LOCAL_OPERATOR = {"user_id": "local-operator", "username": "operator", "display_name": "Local operator",
                  "role": "admin"}
LOCAL_IDENTITY = Identity(**LOCAL_OPERATOR)
PUBLIC_ROUTES = {("GET", "/api/session"), ("POST", "/api/session/login"), ("POST", "/api/session/logout"),
                 ("GET", "/api/public/credit-terms"), ("POST", "/api/public/registrations")}
MESSAGES = {
    "not_signed_in": "Sign in to continue.",
    "session_expired": "Your session has ended. Sign in again to continue.",
    "forbidden": "This page or action is not available to your account.",
    "not_found": "Nothing is available at this address.",
    "accounts_unavailable": "This server runs without accounts.",
    "internal_error": "Something went wrong on the server. Read the page again before trying anything.",
    "account_changed": "This page was opened for another account than the one now signed in on this browser. Nothing "
                       "was read or changed. Reload the page to continue as the account now signed in.",
    "account_binding_required": "This request did not say which account it was made for, so nothing was changed. "
                                "Reload the page and try again.",
}
STATUS_CODES = {401: "not_signed_in", 403: "forbidden", 404: "not_found", 405: "not_found", 413: "payload_too_large",
                415: "invalid_request", 422: "invalid_request"}


class ContractError(Exception):
    """A refusal in the contract's error shape: {contract, code, detail, ...extra}."""

    def __init__(self, status: int, code: str, detail: str | None = None, contract: str | None = None, **extra):
        super().__init__(detail or MESSAGES.get(code, code))
        self.status, self.code, self.detail, self.extra = status, code, detail or MESSAGES.get(code, code), extra
        self.contract = contract  # None: the route's own contract (see contract_for)


def route_kind(method: str, path: str) -> str:
    """public, user, admin or page (a client-build or admin-build file, chosen by role)."""
    if (method, path.rstrip("/") or "/") in PUBLIC_ROUTES:
        return "public"
    if path == "/api/user" or path.startswith("/api/user/"):
        return "user"
    if path == "/api" or path.startswith("/api/"):
        return "admin"
    return "page"


def binding_required(method: str, path: str) -> bool:
    """Whether a request must name its account: every write to a user or administrator route."""
    if method in READ_METHODS:
        return False
    return path == "/api/user" or path.startswith(("/api/user/", "/api/admin/")) or path == "/api/admin"


def binding_checked(method: str, path: str) -> bool:
    """Whether a sent binding is compared with the session: everywhere a session acts, not where one is made or read."""
    return (method, path.rstrip("/") or "/") not in {("GET", "/api/session"), ("POST", "/api/session/login"),
                                                     ("GET", "/api/public/credit-terms"),
                                                     ("POST", "/api/public/registrations")}


def bound_account(values: list[str]) -> str | None:
    """The account a request names: None when it sends no binding; a repeated header names no single account."""
    if not values:
        return None
    return values[0] if len(values) == 1 else ""


def check_binding(method: str, path: str, sent: str | None, identity: Identity | None, require: bool) -> None:
    """Refuse a request bound to another account than the session's and, with ``require``, a write that names no
    account. Runs before the route, so a refused request reads and writes nothing."""
    if identity is None or not binding_checked(method, path):
        return
    if sent is not None and sent != identity.user_id:
        raise ContractError(401, "account_changed", contract=contract_for(path))
    if require and sent is None and binding_required(method, path):
        raise ContractError(428, "account_binding_required", contract=contract_for(path))


def contract_for(path: str) -> str:
    if path.startswith("/api/admin"):
        return ADMIN_CONTRACT
    return ONBOARDING_CONTRACT if path.startswith("/api/public") else USER_CONTRACT


def contract_route(path: str) -> bool:
    """Routes whose every reply, refusals included, is in a contract shape."""
    return path.startswith(("/api/user", "/api/session", "/api/admin", "/api/public"))


def error_response(path: str, status: int, code: str, detail: str, contract: str | None = None,
                   **extra) -> JSONResponse:
    return JSONResponse({"contract": contract or contract_for(path), "code": code, "detail": detail, **extra},
                        status_code=status)


def identity_of(request: Request) -> Identity | None:
    return getattr(request.state, "identity", None)


def session_payload(mode: str, identity: Identity | None, reason: str = "not_signed_in") -> dict:
    if identity is None:
        return {"contract": USER_CONTRACT, "mode": mode, "state": "signed_out", "reason": reason, "user": None,
                "expires_at": None}
    return {"contract": USER_CONTRACT, "mode": mode, "state": "signed_in", "user": identity.view(),
            "expires_at": identity.expires_at}


def local_operator_session() -> dict:
    """GET /api/session on a server without accounts: always the local operator, never expiring."""
    return session_payload("local-operator", LOCAL_IDENTITY)
