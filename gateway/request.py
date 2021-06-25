import logging
import json
import asyncio
from urllib.error import URLError
from typing import Any, Dict, Union

import aiohttp
from bravado_core.spec import Spec
from django.http.request import QueryDict
from rest_framework.request import Request

from gateway import exceptions
from gateway import utils
from core.models import LogicModule
from gateway.clients import SwaggerClient, AsyncSwaggerClient
from datamesh.services import DataMesh

logger = logging.getLogger(__name__)


class GatewayResponse(object):
    """
    Response object used with GatewayRequest
    """

    def __init__(self, content: Any, status_code: int, headers: Dict[str, str]):
        self.content = content
        self.status_code = status_code
        self.headers = headers


class BaseGatewayRequest(object):
    """
    Base class for implementing gateway logic for redirecting incoming request to underlying micro-services.
    First it retrieves a Swagger specification of the micro-service
    to validate incoming request's operation against it.
    """

    SWAGGER_CONFIG = {
        'validate_requests': False,
        'validate_responses': False,
        'use_models': False,
        'validate_swagger_spec': False,
    }

    def __init__(self, request: Request, **kwargs):
        self.request = request
        self.url_kwargs = kwargs
        self._logic_modules = dict()
        self._specs = dict()
        self._data = dict()

    def perform(self):
        raise NotImplementedError('You need to implement this method')

    def _get_logic_module(self, service_name: str) -> LogicModule:
        """ Retrieve LogicModule by service name. """
        if service_name not in self._logic_modules:
            try:
                self._logic_modules[service_name] = LogicModule.objects.get(endpoint_name=service_name)
            except LogicModule.DoesNotExist:
                raise exceptions.ServiceDoesNotExist(f'Service "{service_name}" not found.')
        return self._logic_modules[service_name]

    def get_datamesh(self) -> DataMesh:
        """ Get DataMesh object for the top level model """
        service_name = self.url_kwargs['service']
        logic_module = self._get_logic_module(service_name)

        # find out forwards relations through logic module from request as origin
        padding = self.request.path.index(f'/{logic_module.endpoint_name}')
        endpoint = self.request.path[len(f'/{logic_module.endpoint_name}')+padding:]
        endpoint = endpoint[:endpoint.index('/', 1) + 1]
        return DataMesh(logic_module_endpoint=logic_module.endpoint_name,
                        model_endpoint=endpoint,
                        access_validator=utils.ObjectAccessValidator(self.request))


class GatewayRequest(BaseGatewayRequest):
    """
    Allows to perform synchronous requests to underlying services with requests package
    """

    def perform(self) -> GatewayResponse:
        """
        Make request to underlying service(s) and returns aggregated response.
        """
        # init swagger spec from the service swagger doc file
        try:
            spec = self._get_swagger_spec(self.url_kwargs['service'])
        except exceptions.ServiceDoesNotExist as e:
            return GatewayResponse(e.content, e.status, {'Content-Type': e.content_type})

        # create a client for performing data requests
        client = SwaggerClient(spec, self.request)

        # perform a service data request
        content, status_code, headers = client.request(**self.url_kwargs)

        # aggregate/join with the JoinRecord-models
        if 'join' in self.request.query_params and status_code == 200 and type(content) in [dict, list]:
            try:
                self._join_response_data(resp_data=content)
            except exceptions.ServiceDoesNotExist as e:
                logger.error(e.content)

        if type(content) in [dict, list]:
            content = json.dumps(content, cls=utils.GatewayJSONEncoder)

        return GatewayResponse(content, status_code, headers)

    def _get_swagger_spec(self, endpoint_name: str) -> Spec:
        """Get Swagger spec of specified service."""
        logic_module = self._get_logic_module(endpoint_name)
        schema_url = utils.get_swagger_url_by_logic_module(logic_module)

        if schema_url not in self._specs:
            try:
                # Use stored specification of the module
                spec_dict = logic_module.api_specification

                # Pull specification of the module from its service and store it
                if spec_dict is None:
                    response = utils.get_swagger_from_url(schema_url)
                    spec_dict = response.json()
                    logic_module.api_specification = spec_dict
                    logic_module.save()

            except URLError:
                raise URLError(f'Make sure that {schema_url} is accessible.')

            swagger_spec = Spec.from_dict(spec_dict, config=self.SWAGGER_CONFIG)
            self._specs[schema_url] = swagger_spec

        return self._specs[schema_url]

    def _join_response_data(self, resp_data: Union[dict, list]) -> None:
        """
        Aggregates data from the requested service and from related services.
        Uses DataMesh relationship model for this.
        """
        self.request._request.GET = QueryDict(mutable=True)

        if isinstance(resp_data, dict):
            if 'results' in resp_data:
                # In case of pagination take 'results' as a items data
                resp_data = resp_data.get('results', None)

        datamesh = self.get_datamesh()
        client_map = {}
        for service in datamesh.related_logic_modules:
            spec = self._get_swagger_spec(service)
            client_map[service] = SwaggerClient(spec, self.request)
        datamesh.extend_data(resp_data, client_map)


class AsyncGatewayRequest(BaseGatewayRequest):
    """
    Allows to perform asynchronous requests to underlying services with asyncio and aiohttp package
    """

    def perform(self) -> GatewayResponse:
        """
        Override base class's method for asynchronous execution. Wraps async method.
        """
        result = {}
        asyncio.run(self.async_perform(result))
        if 'response' not in result:
            raise exceptions.GatewayError('Error performing asynchronous gateway request')
        return result['response']

    async def async_perform(self, result: dict):
        try:
            spec = await self._get_swagger_spec(self.url_kwargs['service'])
        except exceptions.ServiceDoesNotExist as e:
            return GatewayResponse(e.content, e.status, {'Content-Type': e.content_type})

        # create a client for performing data requests
        client = AsyncSwaggerClient(spec, self.request)

        # perform a service data request
        content, status_code, headers = await client.request(**self.url_kwargs)

        # aggregate/join with the JoinRecord-models
        if 'join' in self.request.query_params and status_code == 200 and type(content) in [dict, list]:
            try:
                await self._join_response_data(resp_data=content)
            except exceptions.ServiceDoesNotExist as e:
                logger.error(e.content)

        if type(content) in [dict, list]:
            content = json.dumps(content, cls=utils.GatewayJSONEncoder)

        result['response'] = GatewayResponse(content, status_code, headers)

    async def _get_swagger_spec(self, endpoint_name: str) -> Spec:
        """ Gets swagger spec asynchronously and adds it to specs cache """
        logic_module = self._get_logic_module(endpoint_name)
        schema_url = utils.get_swagger_url_by_logic_module(logic_module)

        if schema_url not in self._specs:
            # Use stored specification of the module
            spec_dict = logic_module.api_specification

            # Pull specification of the module from its service and store it
            if spec_dict is None:
                async with aiohttp.ClientSession() as session:
                    async with session.get(schema_url) as response:
                        try:
                            spec_dict = await response.json()
                        except aiohttp.ContentTypeError:
                            raise exceptions.GatewayError(
                                f'Failed to parse swagger schema from {schema_url}. Should be JSON.'
                            )
                    logic_module.api_specification = spec_dict
                    logic_module.save()
                    swagger_spec = Spec.from_dict(spec_dict, config=self.SWAGGER_CONFIG)
                    self._specs[schema_url] = swagger_spec
        return self._specs[schema_url]

    async def _join_response_data(self, resp_data: Union[dict, list]) -> None:
        """
        Aggregates data from the requested service and from related services asynchronously.
        Uses DataMesh relationship model for this.
        """
        self.request._request.GET = QueryDict(mutable=True)

        if isinstance(resp_data, dict):
            if 'results' in resp_data:
                # In case of pagination take 'results' as a items data
                resp_data = resp_data.get('results', None)

        datamesh = self.get_datamesh()
        tasks = []
        for service in datamesh.related_logic_modules:
            tasks.append(self._get_swagger_spec(service))
        # Code executes perfectaly upto this point
        # After that it gives key error
        # Output of task as given when I tested on local for shipment and custodian
        #[<coroutine object AsyncGatewayRequest._get_swagger_spec at 0x7f61f6c31dd0>, <coroutine object AsyncGatewayRequest._get_swagger_spec at 0x7f61f6c317a0>]
        specs = await asyncio.gather(*tasks)
        clients = map(lambda x: AsyncSwaggerClient(x, self.request), specs)
        client_map = dict(zip(datamesh.related_logic_modules, clients))
        await datamesh.async_extend_data(resp_data, client_map)
