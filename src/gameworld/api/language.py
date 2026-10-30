"""Account language at the API boundary (D-25).

Services raise German texts; the handlers here translate ``HTTPException.detail``
and the messages of custom validators (``"Value error, <German text>"``) into the
Nextcloud account language of the requesting account. Status code and headers
stay unchanged (T-06-78). Without a known account the fallback language is used.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from gameworld.access.roles import RolesDep, RoleService, get_role_service
from gameworld.i18n import FALLBACK_LANGUAGE, SOURCE_LANGUAGE, SUPPORTED_LANGUAGES, translate

LOG = logging.getLogger(__name__)

# Replaces pydantic's English-only messages (type, pattern, literal) for de and fr accounts.
MSG_INVALID_INPUT = "Die Eingabe ist ungültig."
# Replaces Starlette's English status phrases (e.g. "Not Found") for de and fr accounts.
MSG_REQUEST_FAILED = "Diese Anfrage kann Gameworld nicht ausführen."

# Set by frontend/src/api.js on every request to the ExApp API.
UI_LANGUAGE_HEADER = "X-Gameworld-Language"

# Prefix pydantic puts in front of the message of a ValueError raised in a validator.
VALUE_ERROR_PREFIX = "Value error, "


async def language_of(scope_user: object, roles: RoleService) -> str:
    """Language of the account in ``scope_user``; never raises."""
    if not isinstance(scope_user, str) or not scope_user:
        return FALLBACK_LANGUAGE
    try:
        return await roles.language(scope_user)
    except Exception as exc:  # the language must never break an answer
        LOG.warning("Account language not determined: %s", type(exc).__name__)
        return FALLBACK_LANGUAGE


def ui_language(request: Request) -> str | None:
    """UI language the frontend sends along (UI_LANGUAGE_HEADER), only for a signed-in account.

    The UI switches with the account language at once, the cached account language
    (CACHE_SECONDS) only later; the header keeps both in step. The language grants
    nothing, so the value is trusted as long as it is one of the supported codes.
    """
    scope_user = request.scope.get("username")
    if not isinstance(scope_user, str) or not scope_user:
        return None
    value = request.headers.get(UI_LANGUAGE_HEADER, "").strip().lower()
    return value if value in SUPPORTED_LANGUAGES else None


async def request_language(request: Request, roles: RolesDep) -> str:
    """FastAPI dependency: UI language of the frontend, else the signed-in account's language, else the fallback."""
    return ui_language(request) or await language_of(request.scope.get("username"), roles)


LangDep = Annotated[str, Depends(request_language)]


async def _handler_language(request: Request) -> str:
    sent = ui_language(request)
    if sent is not None:
        return sent
    try:
        roles = get_role_service()
    except Exception as exc:  # no role service, no account language
        LOG.warning("Role service unavailable for the account language: %s", type(exc).__name__)
        return FALLBACK_LANGUAGE
    return await language_of(request.scope.get("username"), roles)


def translate_validation_message(message: str, language: str) -> str:
    """Translates the text behind ``"Value error, "``.

    pydantic's own messages exist only in English; English accounts keep them,
    the others get MSG_INVALID_INPUT in their language instead of an English text.
    """
    if message.startswith(VALUE_ERROR_PREFIX):
        return VALUE_ERROR_PREFIX + translate(message[len(VALUE_ERROR_PREFIX) :], language)
    if language == "en":
        return message
    return translate(MSG_INVALID_INPUT, language)


async def _translated_http_exception(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 (registered for this type only)
    if isinstance(exc.detail, str):
        language = await _handler_language(request)
        if language != "en" and exc.detail == HTTPStatus(exc.status_code).phrase:
            # Starlette's own English texts (unknown route "Not Found", "Method Not Allowed").
            exc = StarletteHTTPException(exc.status_code, detail=MSG_REQUEST_FAILED, headers=exc.headers)
        if language != SOURCE_LANGUAGE:
            exc = StarletteHTTPException(exc.status_code, detail=translate(exc.detail, language), headers=exc.headers)
    return await http_exception_handler(request, exc)


async def _translated_validation_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 (registered for this type only)
    language = await _handler_language(request)
    errors: list[Any] = []
    for error in exc.errors():
        entry: Any = error
        if isinstance(entry, dict) and isinstance(entry.get("msg"), str):  # pyright: ignore[reportUnknownMemberType]
            entry = {**entry, "msg": translate_validation_message(entry["msg"], language)}  # pyright: ignore[reportUnknownArgumentType]
        errors.append(entry)
    return await request_validation_exception_handler(request, RequestValidationError(errors, body=exc.body))


def install_language_handlers(app: FastAPI) -> None:
    """Registers the translating handlers for HTTPException and request validation errors."""
    app.add_exception_handler(StarletteHTTPException, _translated_http_exception)
    app.add_exception_handler(RequestValidationError, _translated_validation_error)
