import logging
import json
import re
from typing import Any, Dict, Tuple

import requests
import aiohttp
from django.http.request import QueryDict
from bravado_core.spec import Spec
from rest_framework.request import Request
from rest_framework.authentication import get_authorization_header

from . import exceptions

logger = logging.getLogger(__name__)


class BaseSwaggerClient:
    """ Base for client class that is responsible for retrieving data from the service with Swagger spec"""

    def __init__(self, spec: Spec, incoming_request: Request):
        self._spec = spec
        self._in_request = incoming_request
        self._data = dict()

    def request(self, **kwargs):
        raise NotImplementedError()

    def is_valid_for_cache(self) -> bool:
        """ Checks if request is valid for caching operations """
        return (
            self._in_request.method.lower() == 'get'
            and not self._in_request.query_params
        )

    @staticmethod
    def _path_template_to_regex(template: str):
        """Turn a Swagger path template (e.g. /x/{id}/y/) into a matching regex."""
        parts = re.split(r'(\{[^}]+\})', template)
        pattern = ''.join(
            r'[^/]+' if p.startswith('{') and p.endswith('}') else re.escape(p)
            for p in parts
        )
        return re.compile('^' + pattern.rstrip('/') + '/?$')

    def _match_operation(self, spec: Spec, request_method: str, concrete_path: str):
        """
        Resolve the incoming concrete path (e.g. /whats_new/published/latest/) to a
        Swagger operation by matching it against the service's declared path templates.
        A statically-declared route wins over a {param} route.
        """
        paths = spec.spec_dict.get('paths', {})
        candidates = [
            template
            for template in paths
            if self._path_template_to_regex(template).match(concrete_path)
        ]
        # Prefer the most specific template: fewest path params, then longest.
        candidates.sort(key=lambda t: (t.count('{'), -len(t)))

        for template in candidates:
            operation = spec.get_op_for_request(request_method, template)
            if operation is not None:
                return operation
        if request_method == 'OPTIONS':
            for template in candidates:
                operation = spec.get_op_for_request('GET', template)
                if operation is not None:
                    operation.http_method = request_method
                    return operation
        return None

    def prepare_data(self, spec: Spec, **kwargs) -> Tuple[str, str]:
        """ Parse request URL, validate operation, and return method and URL for outgoing request"""

        # Reconstruct the concrete resource path relative to the service, e.g.
        # '/whats_new/published/latest/' or '/whats_new/5/feature_cards/9/'.
        # The gateway view passes the whole remainder as 'path'; DataMesh calls
        # this with 'model' (+ optional 'pk') instead, so support both shapes.
        sub_path = kwargs.get('path')
        if sub_path is None:
            model = (kwargs.get('model') or '').strip('/').lower()
            pk = kwargs.get('pk')
            sub_path = f'{model}/{pk}' if pk is not None else model
        sub_path = sub_path.strip('/')
        concrete_path = f'/{sub_path}/' if sub_path else '/'

        request_method = self._in_request.method
        operation = self._match_operation(spec, request_method, concrete_path)
        if operation is None:
            raise exceptions.EndpointNotFound(
                f'Endpoint not found: {request_method} {concrete_path}'
            )

        method = operation.http_method.lower()

        # Forward the concrete path verbatim to the service
        url = spec.api_url.rstrip('/') + concrete_path
        return method, url

    def get_request_data(self) -> dict:
        """
        Create the data structure to be used in Swagger request. GET and  DELETE
        requests do not require body, so the data structure will have just
        query parameters if passed to swagger request.
        """
        if self._in_request.content_type == 'application/json':
            return json.dumps(self._in_request.data)

        method = self._in_request.META['REQUEST_METHOD'].lower()

        data = {}
        if method in ['post', 'put', 'patch']:
            data = self._in_request.query_params.dict()

            data.pop('aggregate', None)
            data.pop('join', None)

            query_dict_body = (
                self._in_request.data if hasattr(self._in_request, 'data') else dict()
            )
            body = (
                query_dict_body.dict()
                if isinstance(query_dict_body, QueryDict)
                else query_dict_body
            )
            data.update(body)

            # handle uploaded files
            if self._in_request.FILES:
                for key, value in self._in_request.FILES.items():
                    data[key] = {
                        'header': {'Content-Type': value.content_type},
                        'data': value,
                        'filename': value.name,
                    }

        return data

    def get_headers(self) -> dict:
        """Get data and headers from the incoming request."""
        headers = {
            'Authorization': get_authorization_header(self._in_request).decode('utf-8')
        }
        if self._in_request.content_type == 'application/json':
            headers['content-type'] = 'application/json'
        return headers


class SwaggerClient(BaseSwaggerClient):
    """ Synchronous implementation of Swagger client using requests lib """

    def request(self, **kwargs) -> Tuple[Any, int, Dict[str, str]]:
        """
        Perform request to the service, use Swagger spec for validating operation
        """

        method, url = self.prepare_data(self._spec, **kwargs)

        # Check request cache if applicable
        if self.is_valid_for_cache() and url in self._data:
            logger.debug(f'Taking data from cache: {url}')
            return self._data[url]

        # Make request to the service
        method = getattr(requests, method)
        try:
            response = method(
                url,
                headers=self.get_headers(),
                params=self._in_request.query_params,
                data=self.get_request_data(),
                files=self._in_request.FILES,
            )
        except Exception as e:
            error_msg = (
                f'An error occurred when redirecting the request to '
                f'or receiving the response from the service.\n'
                f'Origin: ({e.__class__.__name__}: {e})'
            )
            raise exceptions.GatewayError(error_msg)

        try:
            content = response.json()
        except ValueError:
            content = response.content
        return_data = (content, response.status_code, response.headers)

        # Cache data if request is cache-valid
        if self.is_valid_for_cache():
            self._data[url] = return_data

        return return_data


class AsyncSwaggerClient(BaseSwaggerClient):
    """ Asynchronous implementation of Swagger client using aiohttp lib """

    async def request(self, **kwargs) -> Tuple[Any, int, Dict[str, str]]:
        method, url = self.prepare_data(self._spec, **kwargs)

        # Check request cache if applicable
        if self.is_valid_for_cache() and url in self._data:
            logger.debug(f'Taking data from cache: {url}')
            return self._data[url]

        # Make request to the service
        async with aiohttp.ClientSession() as session:
            method = getattr(session, method)
            if self._in_request.FILES:
                request_data = self.get_request_data()
                data = aiohttp.FormData()
                for field in request_data:
                    if field == 'file':
                        data.add_field('file', request_data['file']['data'].file)
                    else:
                        data.add_field(field, request_data[field])
            else:
                data = self.get_request_data()

            async with method(url, data=data, headers=self.get_headers()) as response:
                try:
                    content = await response.json()
                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                    content = await response.read()

            return_data = (content, response.status, response.headers)

        # Cache data if request is cache-valid
        if self.is_valid_for_cache():
            self._data[url] = return_data

        return return_data
