from __future__ import annotations

import dataclasses
import logging
import typing

from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from web_error import constant
from web_error.error import HttpCodeException, HttpException

if typing.TYPE_CHECKING:
    from starlette.requests import Request

logger_ = logging.getLogger(__name__)


@dataclasses.dataclass
class CorsConfiguration:
    allow_origins: list[str] = dataclasses.field(default_factory=lambda: ["*"])
    allow_methods: list[str] = dataclasses.field(default_factory=lambda: ["*"])
    allow_headers: list[str] = dataclasses.field(default_factory=lambda: ["*"])
    allow_credentials: bool = True


def cors_wrapper_factory(
    cors: CorsConfiguration,
    handler: typing.Callable[[Request, Exception], JSONResponse],
) -> typing.Callable[[Request, Exception], JSONResponse]:
    def wrapper(request: Request, exc: Exception) -> JSONResponse:
        response = handler(request, exc)

        # Since the CORSMiddleware is not executed when an unhandled server exception
        # occurs, we need to manually set the CORS headers ourselves if we want the FE
        # to receive a proper JSON 500, opposed to a CORS error.
        # Setting CORS headers on server errors is a bit of a philosophical topic of
        # discussion in many frameworks, and it is currently not handled in FastAPI.
        # See dotnet core for a recent discussion, where ultimately it was
        # decided to return CORS headers on server failures:
        # https://github.com/dotnet/aspnetcore/issues/2378
        origin = request.headers.get("origin")

        if origin:
            # Have the middleware do the heavy lifting for us to parse
            # all the config, then update our response headers
            mw = CORSMiddleware(
                app=None,
                allow_origins=cors.allow_origins,
                allow_credentials=cors.allow_credentials,
                allow_methods=cors.allow_methods,
                allow_headers=cors.allow_headers,
            )

            # Logic directly from Starlette"s CORSMiddleware:
            # https://github.com/encode/starlette/blob/master/starlette/middleware/cors.py#L152

            response.headers.update(mw.simple_headers)
            has_cookie = "cookie" in request.headers

            # If request includes any cookie headers, then we must respond
            # with the specific origin instead of "*".
            if mw.allow_all_origins and has_cookie:
                response.headers["Access-Control-Allow-Origin"] = origin

            # If we only allow specific origins, then we have to mirror back
            # the Origin header in the response.
            elif not mw.allow_all_origins and mw.is_allowed_origin(origin=origin):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers.add_vary_header("Origin")

        return response

    return wrapper


def exception_handler_factory(
    logger: logging.Logger,
    unhandled_wrappers: dict[str, type[HttpCodeException]],
    *,
    strip_debug: bool = False,
) -> typing.Callable[[Exception], JSONResponse]:
    unhandled_wrappers = unhandled_wrappers or {}

    def exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        wrapper = unhandled_wrappers.get("default")
        ret = wrapper(str(exc)) if wrapper else HttpException("Unhandled exception occurred.", str(exc))
        headers = {}

        if isinstance(exc, HTTPException):
            wrapper = unhandled_wrappers.get(str(exc.status_code))
            debug_message = exc.detail
            ret = (
                wrapper(debug_message)
                if wrapper
                else HttpException("Unhandled HTTPException occurred.", debug_message, status=exc.status_code)
            )
            headers = exc.headers

        if isinstance(exc, HttpException):
            ret = exc

        if ret.status >= constant.SERVER_ERROR:
            logger.exception(ret.message, exc_info=(type(exc), exc, exc.__traceback__))

        if strip_debug and ret.debug_message:
            msg = f"Removed debug message: {ret.debug_message}"
            logger.debug(msg)

        return JSONResponse(
            status_code=ret.status,
            content=ret.marshal(strip_debug=strip_debug),
            headers=headers,
        )

    return exception_handler


def generate_handler(
    logger: logging.Logger = logger_,
    cors: CorsConfiguration | None = None,
    unhandled_wrappers: dict[str, type[HttpCodeException]] | None = None,
    *,
    strip_debug: bool = False,
) -> typing.Callable:
    handler = exception_handler_factory(
        logger=logger,
        unhandled_wrappers=unhandled_wrappers,
        strip_debug=strip_debug,
    )
    return cors_wrapper_factory(cors, handler) if cors else handler
