from django.urls import resolve
from django.test import TestCase


class URLPatternsTest(TestCase):
    def test_api_gateway_urls_with_fragment(self):
        for url in ('/crm/appointment/#some-section', '/crm/appointment#some-section'):
            match = resolve(url)
            self.assertEqual(match.url_name, 'api-gateway')
            self.assertEqual(match.kwargs['service'], 'crm')
            self.assertEqual(match.kwargs['path'].rstrip('/'), 'appointment')
            self.assertEqual(match.kwargs['fragment'], 'some-section')

    def test_api_gateway_urls_with_queryparams(self):
        for url in ('/crm/appointment/?k1=v1&k2=v2', '/crm/appointment?k1=v1&k2=v2'):
            match = resolve(url)
            self.assertEqual(match.url_name, 'api-gateway')
            self.assertEqual(match.kwargs['service'], 'crm')
            self.assertEqual(match.kwargs['path'].rstrip('/'), 'appointment')
            self.assertEqual(match.kwargs['query'], 'k1=v1&k2=v2')

    def test_api_gateway_urls_with_int_pk(self):
        for url in ('/crm/appointment/123456/', '/crm/appointment/123456'):
            match = resolve(url)
            self.assertEqual(match.url_name, 'api-gateway')
            self.assertEqual(match.kwargs['service'], 'crm')
            self.assertEqual(match.kwargs['path'].rstrip('/'), 'appointment/123456')

    def test_api_gateway_urls_with_uuid_pk(self):
        match = resolve('/crm/appointment/39da9369-838e-4750-91a5-f7805cd82839/')
        self.assertEqual(match.url_name, 'api-gateway')
        self.assertEqual(match.kwargs['service'], 'crm')
        self.assertEqual(
            match.kwargs['path'].rstrip('/'),
            'appointment/39da9369-838e-4750-91a5-f7805cd82839',
        )

    def test_api_gateway_urls_without_pk(self):
        for url in ('/crm/appointment/', '/crm/appointment'):
            match = resolve(url)
            self.assertEqual(match.url_name, 'api-gateway')
            self.assertEqual(match.kwargs['service'], 'crm')
            self.assertEqual(match.kwargs['path'].rstrip('/'), 'appointment')

    def test_api_gateway_urls_with_nested_literal_action(self):
        match = resolve('/notification/whats_new/published/latest/')
        self.assertEqual(match.url_name, 'api-gateway')
        self.assertEqual(match.kwargs['service'], 'notification')
        self.assertEqual(
            match.kwargs['path'].rstrip('/'), 'whats_new/published/latest'
        )

    def test_api_gateway_urls_with_detail_action(self):
        match = resolve('/notification/whats_new/1/publish/')
        self.assertEqual(match.url_name, 'api-gateway')
        self.assertEqual(match.kwargs['service'], 'notification')
        self.assertEqual(match.kwargs['path'].rstrip('/'), 'whats_new/1/publish')

    def test_api_gateway_urls_with_nested_subresource(self):
        match = resolve('/notification/whats_new/1/feature_cards/9/')
        self.assertEqual(match.url_name, 'api-gateway')
        self.assertEqual(match.kwargs['service'], 'notification')
        self.assertEqual(
            match.kwargs['path'].rstrip('/'), 'whats_new/1/feature_cards/9'
        )

    def test_api_gateway_async_urls_with_nested_subresource(self):
        match = resolve('/async/notification/whats_new/1/feature_cards/9/')
        self.assertEqual(match.url_name, 'api-gateway-async')
        self.assertEqual(match.kwargs['service'], 'notification')
        self.assertEqual(
            match.kwargs['path'].rstrip('/'), 'whats_new/1/feature_cards/9'
        )

    def test_admin_url(self):
        match = resolve('/admin/')
        self.assertEqual(match.namespace, 'admin')
        self.assertEqual(match.url_name, 'index')

    def test_docs_swagger(self):
        match = resolve('/docs/')
        self.assertEqual(match.url_name, 'schema-swagger-ui')

    def test_docs_swagger_json(self):
        match = resolve('/docs/swagger.json')
        self.assertEqual(match.url_name, 'schema-swagger-json')
