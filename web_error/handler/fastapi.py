from __future__ import annotations

import json
import logging
import typing

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from web_error import constant
from web_error.error import HttpException
from web_error.handler import starlette

logger = logging.getLogger(__name__)


def _handle_exception(exc: Exception, *, debug_enabled: bool = True) -> tuple[dict, str]:
    status = constant.SERVER_ERROR
    message = "Unhandled exception occurred."
    response = {
        "message": message,
        "debug_message": str(exc),
        "code": None,
    }
    headers = {}

    if isinstance(exc, HTTPException):
        response["message"] = exc.detail
        status = exc.status_code
        headers = exc.headers

    if isinstance(exc, RequestValidationError):
        response["message"] = "Request validation error."
        response["debug_message"] = json.loads(json.dumps(exc.errors(), default=str))
        status = 422

    if isinstance(exc, HttpException):
        response = exc.marshal()
        status = exc.status

    if status >= constant.SERVER_ERROR:
        logger.exception(message, exc_info=(type(exc), exc, exc.__traceback__))

    if not debug_enabled:
        debug_message = response.pop("debug_message", None)
        if debug_message:
            msg = f"Removed debug message: {debug_message}"
            logger.debug(msg)

    return response, status, headers


class ExceptionHandler:
    def __init__(
        self: typing.Self,
        unhandled_code: str,
        request_validation_code: str,
        *,
        debug_enabled: bool = True,
    ) -> None:
        self.unhandled_code = unhandled_code
        self.request_validation_code = request_validation_code
        self.debug_enabled = debug_enabled

    def __call__(self: typing.Self, request: starlette.Request, exc: Exception) -> starlette.JSONResponse:  # noqa: ARG002
        response, status, headers = _handle_exception(exc, debug_enabled=self.debug_enabled)

        if response["code"] is None:
            response["code"] = self.request_validation_code if status == 422 else self.unhandled_code  # noqa: PLR2004

        return starlette.JSONResponse(
            status_code=status,
            content=response,
        )


def exception_handler(request: starlette.Request, exc: Exception) -> starlette.JSONResponse:  # noqa: ARG001
    response, status, headers = _handle_exception(exc)

    return starlette.JSONResponse(
        status_code=status,
        content=response,
        headers=headers,
    )


def generate_handler_with_cors(
    allow_origins: list[str] | None = None,
    allow_methods: list[str] | None = None,
    allow_headers: list[str] | None = None,
    *,
    allow_credentials: bool = True,
) -> starlette.JSONResponse:
    return starlette.generate_handler_with_cors(
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
        _exception_handler=exception_handler,
    )
