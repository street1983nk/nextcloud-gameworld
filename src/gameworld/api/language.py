"""Account language at the API boundary (D-25).

Services raise German texts; the handlers here translate ``HTTPException.detail``
and the messages of custom validators (``"Value error, <German text>"``) into the
Nextcloud account language of the requesting account. Status code and headers
stay unchanged (T-06-78). Without a known account the fallback language is used.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from gameworld.access.roles import RolesDep, RoleService, get_role_service
from gameworld.i18n import FALLBACK_LANGUAGE, SOURCE_LANGUAGE, translate

LOG = logging.getLogger(__name__)

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


async def request_language(request: Request, roles: RolesDep) -> str:
    """FastAPI dependency: language of the signed-in account (scope["username"]), else the fallback."""
    return await language_of(request.scope.get("username"), roles)


LangDep = Annotated[str, Depends(request_language)]


async def _handler_language(request: Request) -> str:
    try:
        roles = get_role_service()
    except Exception as exc:  # no role service, no account language
        LOG.warning("Role service unavailable for the account language: %s", type(exc).__name__)
        return FALLBACK_LANGUAGE
    return await language_of(request.scope.get("username"), roles)


def translate_validation_message(message: str, language: str) -> str:
    """Translates the text behind ``"Value error, "``; pydantic's own English messages stay as they are."""
    if message.startswith(VALUE_ERROR_PREFIX):
        return VALUE_ERROR_PREFIX + translate(message[len(VALUE_ERROR_PREFIX) :], language)
    return translate(message, language)


async def _translated_http_exception(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 (registered for this type only)
    if isinstance(exc.detail, str):
        language = await _handler_language(request)
        if language != SOURCE_LANGUAGE:
            exc = StarletteHTTPException(exc.status_code, detail=translate(exc.detail, language), headers=exc.headers)
    return await http_exception_handler(request, exc)


async def _translated_validation_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 (registered for this type only)
    language = await _handler_language(request)
    if language == SOURCE_LANGUAGE:
        return await request_validation_exception_handler(request, exc)
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
