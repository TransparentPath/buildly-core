from unittest import mock

import pytest

from django.core.handlers.wsgi import WSGIRequest
from rest_framework.test import APIRequestFactory


@pytest.fixture(scope='session')
def request_factory():
    return APIRequestFactory()


@pytest.fixture
def mock_uom_lookup():
    """
    Stub the unit-of-measure lookups in `core.serializers`.

    `CoreUserWritableSerializer.create` calls `requests.get` against
    `settings.TP_SHIPMENT_URL` (core/serializers.py:229-230) with no mocking, so
    the registration tests only passed while a live third-party dev environment
    happened to be up and answering. An empty result exercises the serializer's
    own documented fallbacks (America/Los_Angeles / English).
    """
    with mock.patch('core.serializers.requests.get') as mocked_get:
        mocked_get.return_value.json.return_value = []
        yield mocked_get


@pytest.fixture(scope='session')
def wsgi_request_factory():
    def _make_wsgi_request(data: dict = None):
        environ = {
            'REQUEST_METHOD': 'get',
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': 8080,
            'wsgi.input': '',
        }
        if data:
            environ.update(data)

        return WSGIRequest(environ)

    return _make_wsgi_request
