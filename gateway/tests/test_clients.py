import os
import asyncio
from unittest.mock import patch

import pytest
import httpretty
from bravado_core.spec import Spec
from django.contrib.auth.models import AnonymousUser

import factories
from core.tests.fixtures import auth_api_client, logic_module  # noqa: F401
from gateway.clients import BaseSwaggerClient, AsyncSwaggerClient
from gateway.request import BaseGatewayRequest


CURRENT_PATH = os.path.dirname(os.path.abspath(__file__))

CORE_USER_UUID_HEADER = 'X-Core-User-Uuid'
CORE_ORGANIZATION_UUID_HEADER = 'X-Core-Organization-Uuid'

# A downstream Django service reads a forwarded header under this META key.
# notification_service runs with JWT_AUTH_DISABLED and only claims the `Token`
# scheme, so the forwarded `Authorization` never identifies the caller there --
# this is the key the per-user notification state has to key on.
CORE_USER_UUID_META_KEY = 'HTTP_X_CORE_USER_UUID'


def _swagger_spec():
    """Build a real Spec from the documents fixture, as the gateway does."""
    import json

    with open(os.path.join(CURRENT_PATH, 'fixtures/swagger_documents.json')) as r:
        spec_dict = json.load(r)
    return Spec.from_dict(
        spec_dict,
        origin_url='http://documentservice:8080/docs/swagger.json',
        config=BaseGatewayRequest.SWAGGER_CONFIG,
    )


def _client_for(request_factory, user, extra=None):
    """A gateway client wrapping a DRF request authenticated as `user`."""
    from rest_framework.request import Request

    django_request = request_factory.get('/documents/1/', **(extra or {}))
    drf_request = Request(django_request)
    drf_request.user = user
    return BaseSwaggerClient(spec=None, incoming_request=drf_request)


# ---------------------------------------------------------------------------
# What the gateway asserts about the caller it has already verified
# ---------------------------------------------------------------------------


@pytest.mark.django_db()
def test_get_headers_forwards_verified_core_user_uuid(request_factory):
    """
    The gateway holds an authenticated CoreUser; the downstream service must be
    told which user it is. `core_user_uuid` is the unique, always-populated,
    API-read-only field a notification row keys on.
    """
    user = factories.CoreUser.create()
    client = _client_for(request_factory, user)

    headers = client.get_headers()

    assert headers[CORE_USER_UUID_HEADER] == str(user.core_user_uuid)


@pytest.mark.django_db()
def test_get_headers_forwards_verified_organization_uuid(request_factory):
    user = factories.CoreUser.create()
    client = _client_for(request_factory, user)

    headers = client.get_headers()

    assert headers[CORE_ORGANIZATION_UUID_HEADER] == str(
        user.organization.organization_uuid
    )


@pytest.mark.django_db()
def test_get_headers_identity_values_are_strings(request_factory):
    """
    `core_user_uuid` is a CharField with a `uuid.uuid4` default, so it holds a
    `UUID` object until it round-trips through the database, and
    `organization_uuid` is a real UUIDField. aiohttp rejects non-str header
    values outright, so the gateway has to stringify them.
    """
    user = factories.CoreUser.create()
    assert not isinstance(
        user.core_user_uuid, str
    ), 'fixture no longer reproduces the un-stringified case'

    client = _client_for(request_factory, user)
    headers = client.get_headers()

    for name, value in headers.items():
        assert isinstance(value, str), f'{name} is {type(value)}, not str'


# ---------------------------------------------------------------------------
# A client must not be able to supply its own identity
# ---------------------------------------------------------------------------


@pytest.mark.django_db()
def test_get_headers_ignores_client_supplied_identity_headers(request_factory):
    """
    The whole point of forwarding a gateway-asserted identity: a caller that
    sends the header itself must not be able to act as another user. The
    outgoing header set is built from `request.user`, never copied from the
    incoming request, so the spoofed value is simply not forwarded.
    """
    victim = factories.CoreUser.create(username='victim')
    attacker = factories.CoreUser.create(username='attacker')

    client = _client_for(
        request_factory,
        attacker,
        extra={
            'HTTP_X_CORE_USER_UUID': str(victim.core_user_uuid),
            'HTTP_X_CORE_ORGANIZATION_UUID': str(
                victim.organization.organization_uuid
            ),
        },
    )

    headers = client.get_headers()

    assert headers[CORE_USER_UUID_HEADER] == str(attacker.core_user_uuid)
    assert headers[CORE_USER_UUID_HEADER] != str(victim.core_user_uuid)


@pytest.mark.django_db()
def test_get_headers_omits_identity_for_unauthenticated_request(request_factory):
    """
    The gateway views require IsAuthenticated, so this is defence in depth: an
    anonymous request must yield no identity header at all rather than a
    header saying `None`, which a service could mistake for a real user.
    """
    client = _client_for(request_factory, AnonymousUser())

    headers = client.get_headers()

    assert CORE_USER_UUID_HEADER not in headers
    assert CORE_ORGANIZATION_UUID_HEADER not in headers


@pytest.mark.django_db()
def test_get_headers_omits_organization_when_user_has_none(request_factory):
    """`CoreUser.organization` is nullable; omit rather than send 'None'."""
    user = factories.CoreUser.create(username='orgless', organization=None)
    client = _client_for(request_factory, user)

    headers = client.get_headers()

    assert headers[CORE_USER_UUID_HEADER] == str(user.core_user_uuid)
    assert CORE_ORGANIZATION_UUID_HEADER not in headers


# ---------------------------------------------------------------------------
# End to end: the identity really reaches the service, on both transports
# ---------------------------------------------------------------------------


@pytest.mark.django_db()
@httpretty.activate
def test_service_receives_identity_through_the_gateway(auth_api_client, logic_module):
    """
    Drive a real proxied request and assert on what the service was sent, in
    the form a downstream Django service reads it.
    """
    with open(os.path.join(CURRENT_PATH, 'fixtures/swagger_documents.json')) as r:
        swagger_body = r.read()
    httpretty.register_uri(
        httpretty.GET,
        f'{logic_module.endpoint}/docs/swagger.json',
        body=swagger_body,
        adding_headers={'Content-Type': 'application/json'},
    )
    httpretty.register_uri(
        httpretty.GET,
        f'{logic_module.endpoint}/thumbnail/1/',
        body='{"details": "IT IS A TEST"}',
        adding_headers={'Content-Type': 'application/json'},
    )

    response = auth_api_client.get(f'/{logic_module.endpoint_name}/thumbnail/1/')
    assert response.status_code == 200

    user = auth_api_client.handler._force_user
    received = httpretty.last_request().headers

    assert received[CORE_USER_UUID_HEADER] == str(user.core_user_uuid)
    # The same header as a downstream Django service sees it.
    wsgi_meta = {
        f'HTTP_{name.upper().replace("-", "_")}': value
        for name, value in received.items()
    }
    assert wsgi_meta[CORE_USER_UUID_META_KEY] == str(user.core_user_uuid)


@pytest.mark.django_db()
@httpretty.activate
def test_service_does_not_receive_client_supplied_identity_through_the_gateway(
    auth_api_client, logic_module
):
    """The spoofing case, end to end through the real view stack."""
    victim = factories.CoreUser.create(username='victim')

    with open(os.path.join(CURRENT_PATH, 'fixtures/swagger_documents.json')) as r:
        swagger_body = r.read()
    httpretty.register_uri(
        httpretty.GET,
        f'{logic_module.endpoint}/docs/swagger.json',
        body=swagger_body,
        adding_headers={'Content-Type': 'application/json'},
    )
    httpretty.register_uri(
        httpretty.GET,
        f'{logic_module.endpoint}/thumbnail/1/',
        body='{"details": "IT IS A TEST"}',
        adding_headers={'Content-Type': 'application/json'},
    )

    response = auth_api_client.get(
        f'/{logic_module.endpoint_name}/thumbnail/1/',
        HTTP_X_CORE_USER_UUID=str(victim.core_user_uuid),
    )
    assert response.status_code == 200

    caller = auth_api_client.handler._force_user
    received = httpretty.last_request().headers

    assert received[CORE_USER_UUID_HEADER] == str(caller.core_user_uuid)
    assert received[CORE_USER_UUID_HEADER] != str(victim.core_user_uuid)


@pytest.mark.django_db()
def test_async_client_sends_identity_headers_to_the_service(request_factory):
    """
    The async transport shares `get_headers`, but aiohttp is stricter than
    requests about header value types, so prove the async wire too.

    Deliberately does not use the `event_loop` fixture: pytest-asyncio 1.x
    removed it, which is why gateway/tests/test_views_async.py errors at
    collection on this pinned toolchain.
    """
    from rest_framework.request import Request

    user = factories.CoreUser.create()
    django_request = request_factory.get('/documents/1/')
    drf_request = Request(django_request)
    drf_request.user = user

    client = AsyncSwaggerClient(
        spec=_swagger_spec(), incoming_request=drf_request
    )

    sent = {}

    class _FakeResponse:
        status = 200
        headers = {'Content-Type': 'application/json'}

        async def json(self):
            return {'details': 'IT IS A TEST'}

    class _FakeCtx:
        async def __aenter__(self):
            return _FakeResponse()

        async def __aexit__(self, *exc):
            return False

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, **kwargs):
            sent['url'] = url
            sent['headers'] = kwargs.get('headers')
            return _FakeCtx()

    with patch('gateway.clients.aiohttp.ClientSession', return_value=_FakeSession()):
        asyncio.run(client.request(path='thumbnail/1'))

    assert sent['headers'][CORE_USER_UUID_HEADER] == str(user.core_user_uuid)
    # aiohttp itself would reject a UUID object here.
    assert all(isinstance(v, str) for v in sent['headers'].values())
