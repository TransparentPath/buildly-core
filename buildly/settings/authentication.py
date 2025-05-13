import ldap

from .base import *
from django_auth_ldap.config import LDAPSearch

MIDDLEWARE_AUTHENTICATION = [
    'oauth2_provider.middleware.OAuth2TokenMiddleware',
]

MIDDLEWARE = MIDDLEWARE_DJANGO + MIDDLEWARE_AUTHENTICATION

# Authentication backends
# https://docs.djangoproject.com/en/1.11/ref/settings/#std:setting-AUTHENTICATION_BACKENDS

AUTHENTICATION_LDAP_BACKEND = []
AUTH_LDAP_ENABLE = True if os.getenv('LDAP_ENABLE') == 'True' else False
if AUTH_LDAP_ENABLE:
    AUTHENTICATION_LDAP_BACKEND.append('django_auth_ldap.backend.LDAPBackend')

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'oauth2_provider.backends.OAuth2Backend',
]

AUTHENTICATION_BACKENDS = AUTHENTICATION_LDAP_BACKEND + AUTHENTICATION_BACKENDS

# Rest Framework OAuth2 and JWT
REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] += [
    'oauth2_provider.contrib.rest_framework.OAuth2Authentication',
]

# Auth Application
OAUTH_CLIENT_ID = os.getenv('OAUTH_CLIENT_ID', None)
OAUTH_CLIENT_SECRET = os.getenv('OAUTH_CLIENT_SECRET', None)

# JWT Authentication settings
JWT_PAYLOAD_ENRICHER = 'core.jwt_utils.payload_enricher'
JWT_ISSUER = os.getenv('JWT_ISSUER', '')
JWT_ALLOWED_ISSUER = os.getenv('JWT_ISSUER', '')
JWT_AUTH_DISABLED = False
JWT_PRIVATE_KEY_RSA_BUILDLY = os.getenv('JWT_PRIVATE_KEY_RSA_BUILDLY', '').replace('\\n', '\n')
JWT_PUBLIC_KEY_RSA_BUILDLY = os.getenv('JWT_PUBLIC_KEY_RSA_BUILDLY', '').replace('\\n', '\n')

# Password Validators
AUTH_PASSWORD_VALIDATORS = []

AUTH_PASSWORD_VALIDATORS_MAP = {
    'USE_PASSWORD_USER_ATTRIBUTE_SIMILARITY_VALIDATOR': {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'
    },
    'USE_PASSWORD_MINIMUM_LENGTH_VALIDATOR': {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': int(os.getenv('PASSWORD_MINIMUM_LENGTH', 6))},
    },
    'USE_PASSWORD_COMMON_VALIDATOR': {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'
    },
    'USE_PASSWORD_NUMERIC_VALIDATOR': {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'
    },
}

for (
    password_validator_env_var,
    password_validator,
) in AUTH_PASSWORD_VALIDATORS_MAP.items():
    if os.getenv(password_validator_env_var, 'True') == 'True':
        AUTH_PASSWORD_VALIDATORS.append(password_validator)

LOGIN_URL = os.getenv('LOGIN_URL', FRONTEND_URL)
LOGIN_REDIRECT_URL = '/'

# oauth2 settings
OAUTH2_PROVIDER = {
    'ACCESS_TOKEN_EXPIRE_SECONDS': int(os.getenv('ACCESS_TOKEN_EXPIRE_SECONDS', 36000)),
    'SCOPES': {
        'read': 'Read scope',
        'write': 'Write scope',
        'introspection': 'Introspect token scope',
    },
}

DEFAULT_OAUTH_DOMAINS = os.getenv('DEFAULT_OAUTH_DOMAINS', '')
CREATE_DEFAULT_PROGRAM = (
    True if os.getenv('CREATE_DEFAULT_PROGRAM') == 'True' else False
)

# LDAP configuration
# https://django-auth-ldap.readthedocs.io/en/latest/reference.html#settings

if AUTH_LDAP_ENABLE:
    AUTH_LDAP_SERVER_URI = os.environ.get('LDAP_HOST')
    AUTH_LDAP_BIND_DN = os.environ.get('LDAP_USERNAME')  # Bind Distinguished Name(DN)
    AUTH_LDAP_BIND_PASSWORD = os.environ.get('LDAP_PASSWORD')
    AUTH_LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN')
    AUTH_LDAP_USERNAME_FIELD_SEARCH = os.environ.get('LDAP_USERNAME_FIELD_SEARCH')

    AUTH_LDAP_USER_SEARCH = LDAPSearch(
        AUTH_LDAP_BASE_DN,
        ldap.SCOPE_SUBTREE,
        f'{AUTH_LDAP_USERNAME_FIELD_SEARCH}=%(user)s',
    )

    AUTH_LDAP_USER_ATTR_MAP = {
        'username': AUTH_LDAP_USERNAME_FIELD_SEARCH,
        'first_name': 'givenName',
        'last_name': 'sn',
        'email': 'mail',
    }
    AUTH_LDAP_ALWAYS_UPDATE_USER = True
    AUTH_LDAP_CACHE_TIMEOUT = (
        3600
    )  # Cache distinguished names and group memberships for an hour to minimize
