import http
import json
from unittest import mock

import httpx
from starlette.applications import Starlette
from starlette.exceptions import HTTPException

from web_error import constant, error
from web_error.cors import CorsConfiguration
from web_error.handler import starlette


class ATestError(error.ServerException):
    message = "This is an error."
    code = "E123"


class UnhandledException(error.ServerException):
    code = "E000"
    message = "Unhandled exception occurred."


class ValidationError(error.HttpCodeException):
    status = 422
    code = "E001"
    message = "Request validation error."


class TestExceptionHandler:
    def test_unexpected_error_replaces_code(self):
        logger = mock.Mock()

        request = mock.Mock()
        exc = Exception("Something went bad")

        eh = starlette.generate_handler(
            logger=logger,
            unhandled_wrappers={
                "default": UnhandledException,
            },
        )
        response = eh(request, exc)

        assert response.status_code == constant.SERVER_ERROR
        assert json.loads(response.body) == {
            "message": "Unhandled exception occurred.",
            "debug_message": "Something went bad",
            "code": "E000",
        }
        assert logger.exception.call_args == mock.call(
            "Unhandled exception occurred.",
            exc_info=(type(exc), exc, None),
        )

    def test_debug_disabled(self):
        request = mock.Mock()
        exc = Exception("Something went bad")

        eh = starlette.generate_handler(
            strip_debug=True,
            unhandled_wrappers={
                "default": UnhandledException,
            },
        )
        response = eh(request, exc)

        assert response.status_code == constant.SERVER_ERROR
        assert json.loads(response.body) == {
            "message": "Unhandled exception occurred.",
            "code": "E000",
        }

    def test_unexpected_error(self):
        logger = mock.Mock()

        request = mock.Mock()
        exc = Exception("Something went bad")

        eh = starlette.generate_handler(logger=logger)
        response = eh(request, exc)

        assert response.status_code == constant.SERVER_ERROR
        assert json.loads(response.body) == {
            "message": "Unhandled exception occurred.",
            "debug_message": "Something went bad",
            "code": None,
        }
        assert logger.exception.call_args == mock.call(
            "Unhandled exception occurred.",
            exc_info=(type(exc), exc, None),
        )

    def test_known_error(self):
        request = mock.Mock()
        exc = ATestError("something bad")

        eh = starlette.generate_handler()
        response = eh(request, exc)

        assert response.status_code == constant.SERVER_ERROR
        assert json.loads(response.body) == {
            "message": "This is an error.",
            "debug_message": "something bad",
            "code": "E123",
        }

    def test_starlette_error(self):
        request = mock.Mock()
        exc = HTTPException(constant.NOT_FOUND, "something bad")

        eh = starlette.generate_handler()
        response = eh(request, exc)

        assert response.status_code == constant.NOT_FOUND
        assert json.loads(response.body) == {
            "message": "Unhandled HTTPException occurred.",
            "debug_message": exc.detail,
            "code": None,
        }

    def test_starlette_error_with_headers(self):
        request = mock.Mock()
        exc = HTTPException(
            status_code=http.HTTPStatus.UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

        eh = starlette.generate_handler()
        response = eh(request, exc)

        assert response.status_code == http.HTTPStatus.UNAUTHORIZED
        assert json.loads(response.body) == {
            "message": "Unhandled HTTPException occurred.",
            "debug_message": exc.detail,
            "code": None,
        }
        assert response.headers["www-authenticate"] == "Basic"

    def test_cors_no_origin(self):
        request = mock.Mock(headers={})
        exc = ATestError("something bad")
        cors = CorsConfiguration()

        eh = starlette.generate_handler(cors=cors)
        response = eh(request, exc)

        assert "access-control-allow-origin" not in response.headers

    def test_error_with_origin(self):
        request = mock.Mock(headers={"origin": "localhost"})
        exc = ATestError("something bad")
        cors = CorsConfiguration()

        eh = starlette.generate_handler(cors=cors)
        response = eh(request, exc)

        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "*"

    def test_error_with_origin_and_cookie(self):
        request = mock.Mock(headers={"origin": "localhost", "cookie": "something"})
        exc = ATestError("something bad")

        cors = CorsConfiguration()

        eh = starlette.generate_handler(cors=cors)
        response = eh(request, exc)

        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "localhost"

    def test_missing_token_with_origin_limited_origins(self):
        request = mock.Mock(headers={"origin": "localhost", "cookie": "something"})
        exc = ATestError("something bad")

        cors = CorsConfiguration(allow_origins=["localhost"])

        eh = starlette.generate_handler(cors=cors)
        response = eh(request, exc)

        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "localhost"

    def test_missing_token_with_origin_limited_origins_no_match(self):
        request = mock.Mock(headers={"origin": "localhost2", "cookie": "something"})
        exc = ATestError("something bad")

        cors = CorsConfiguration(allow_origins=["localhost"])

        eh = starlette.generate_handler(cors=cors)
        response = eh(request, exc)

        assert "access-control-allow-origin" not in response.headers


async def test_exception_handler_in_app():
    exception_handler = starlette.generate_handler(
        unhandled_wrappers={
            "default": UnhandledException,
        },
    )

    app = Starlette(
        exception_handlers={
            Exception: exception_handler,
            HTTPException: exception_handler,
        },
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=("1.2.3.4", 123))
    client = httpx.AsyncClient(transport=transport, app=app, base_url="https://test")

    r = await client.get("/endpoint")
    assert r.json() == {
        "code": None,
        "message": "Unhandled HTTPException occurred.",
        "debug_message": "Not Found",
    }
