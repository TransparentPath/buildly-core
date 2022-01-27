# buildly
[![Docker Pulls](https://img.shields.io/docker/pulls/buildly/buildly.svg)](https://hub.docker.com/r/buildly/buildly/) [![Build Status](https://travis-ci.org/buildlyio/buildly-core.svg?branch=master)](https://travis-ci.org/buildlyio/buildly-core) [![Documentation Status](https://readthedocs.org/projects/buildly-core/badge/?version=latest)](https://buildly-core.readthedocs.io/en/latest/?badge=latest) [![Gitter](https://badges.gitter.im/Buildlyio/community.svg)](https://gitter.im/Buildlyio/community?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge)

A gateway and service discovery system for “micro” services. A light weight Gateway that connects all of your data services, API’s and endpoints to a single easy-to-use URL.

Public Roadmap - https://docs.google.com/spreadsheets/d/1tnmAy-tiQOVWSAigJIQ5HhdatbE3WTC00tzdwtOe2Hk

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes. See deployment for notes on how to deploy the project on a live system.

### Prerequisites

* Docker version 19+

### Installing

Build first the image:

```bash
docker-compose build # --no-cache to force dependencies installation
```

To run the webserver (go to 127.0.0.1:8080):

```bash
docker-compose up # -d for detached
```

User: `admin`
Password: `admin`.

To run the webserver with pdb support:

```bash
docker-compose run --rm --service-ports buildly
```

## Running the tests

To run the tests without flake8:

```bash
docker-compose run --entrypoint '/usr/bin/env' --rm buildly bash scripts/run-tests.sh --keepdb
```

To run the tests like if it was CI with flake8:

```bash
docker-compose run --entrypoint '/usr/bin/env' --rm buildly bash scripts/run-tests.sh --ci
```

See `pytest --help` for more options.

## Deployment

The instructions in the next three subsections [Configure the API authentication](#configure-the-api-authentication), [Generating RSA keys](#generating-rsa-keys), and [Configuration](#configuration) will explain how to configure a Buildly Core instance to have it on a live system.

### Configure the API authentication

All clients interact with our API using the OAuth2 protocol. In order to configure it, go to `admin/oauth2_provider/application/` and add a new application there.

### Generating RSA keys

For using JWT as authentication method, we need to configure public and
private RSA keys.

The following commands will generate a public and private key. The private
key will stay in Buildly and the public one will be supplied to
microservices in order to verify the authenticity of the message:

```bash
$ openssl genrsa -out private.pem 2048
$ openssl rsa -in private.pem -outform PEM -pubout -out public.pem
```

### Configuration

Specify each parameter using `-e`, `--env`, and `--env-file` flags to set simple (non-array) environment variables to `docker run`. For example,

```bash
$ docker run -e MYVAR1 --env MYVAR2=foo \
    --env-file ./env.list \
    buildly/buildly:<version>
```

The following tables list the configurable parameters of buildly and their default values.

#### Security System
|             Parameter               |            Description             |                    Default                |
|-------------------------------------|------------------------------------|-------------------------------------------|
| `ALLOWED_HOSTS`                     | A list of strings representing the domain names the app can serve  | `[]`      |
| `CORS_ORIGIN_ALLOW_ALL`             | If True, CORS_ORIGIN_WHITELIST is not used and all origins are accepted  | False |
| `CORS_ORIGIN_WHITELIST`             | A list of origins that are authorized to make cross-site HTTP requests  | `[]` |
| `DEFAULT_ORG`                       | The first organization created in the database  | ``                           |
| `SECRET_KEY`                        | Used to provide cryptographic signing, and should be set to a unique, unpredictable value | None |
| `SUPER_USER_PASSWORD`               | Used to define the super user password when it's created for the first time | `admin` in Debug mode or None |

#### Database Connection
|             Parameter               |            Description             |                    Default                |
|-------------------------------------|------------------------------------|-------------------------------------------|
| `DATABASE_ENGINE`                   | The database backend to use. (`postgresql`, `mysql`, `sqlite3` or `oracle`) | `` |
| `DATABASE_NAME`                     | The name of the database to use          | ``                                  |
| `DATABASE_USER`                     | The username to use when connecting to the database | ``                       |
| `DATABASE_PASSWORD`                 | The password to use when connecting to the database | ``                       |
| `DATABASE_HOST`                     | The host to use when connecting to the database | ``                           |
| `DATABASE_PORT`                     | The port to use when connecting to the database | ``                           |

#### Authentication System
|             Parameter               |            Description             |                    Default                |
|-------------------------------------|------------------------------------|-------------------------------------------|
| `ACCESS_TOKEN_EXPIRE_SECONDS`       | The number of seconds an access token remains valid | 3600                     |
| `JWT_ISSUER`                        | The name of the JWT issuer               | ``                                  |
| `JWT_PRIVATE_KEY_RSA_BUILDLY`       | The private RSA KEY                      | ``                                  |
| `JWT_PUBLIC_KEY_RSA_BUILDLY`        | The public RSA KEY                       | ``                                  |
| `OAUTH_CLIENT_ID`                   | Used in combination with OAUTH_CLIENT_SECRET to create OAuth2 password grant | None |
| `OAUTH_CLIENT_SECRET`               | Used in combination with OAUTH_CLIENT_ID to create OAuth2 password grant | None |
| `PASSWORD_MINIMUM_LENGTH`           | The minimum length of passwords      | `6` |
| `USE_PASSWORD_MINIMUM_LENGTH_VALIDATOR`   | Checks whether the password meets a minimum length | True       |
| `USE_PASSWORD_USER_ATTRIBUTE_SIMILARITY_VALIDATOR`  | Checks the similarity between the password and a set of attributes of the user | True |
| `USE_PASSWORD_COMMON_VALIDATOR`     | Checks whether the password occurs in a list of common passwords | True |
| `USE_PASSWORD_NUMERIC_VALIDATOR`    | Checks whether the password isn’t entirely numeric | True |
| `SOCIAL_AUTH_GITHUB_REDIRECT_URL`   | The redirect URL for GitHub Social auth  | None                                |
| `SOCIAL_AUTH_GOOGLE_OAUTH2_REDIRECT_URL`  | The redirect URL for Google Social auth  | None                          |
| `SOCIAL_AUTH_LOGIN_REDIRECT_URL`    | Redirect the user once the auth process ended successfully | None                              |
| `SOCIAL_AUTH_MICROSOFT_GRAPH_REDIRECT_URL` | The redirect URL for Microsoft graph Social auth | None                 |

#### LDAP & Active Directory Server
|             Parameter               |            Description             |                    Default                |
|-------------------------------------|------------------------------------|-------------------------------------------|
| `LDAP_ENABLE`                       | If true, enable LDAP authentication  | False |
| `LDAP_HOST`                         | The host to use when connecting to the LDAP server | `` |
| `LDAP_USERNAME`                     | The username to use when connecting to the LDAP server  | `` |
| `LDAP_PASSWORD`                     | The password to use when connecting to the LDAP server | `` |
| `LDAP_BASE_DN`                      | The base domain name for search | `` |
| `LDAP_USERNAME_FIELD_SEARCH`        | The username field used by the LDAP server for search | `` |

#### Email Server
|             Parameter               |            Description             |                    Default                |
|-------------------------------------|------------------------------------|-------------------------------------------|
| `EMAIL_BACKEND`                     | If `SMTP`, enable connection to an SMTP Server  | `` |
| `EMAIL_HOST`                        | The host to use for sending email server | `` |
| `EMAIL_HOST_USER`                   | The username to use when connecting to the SMTP server  | `` |
| `EMAIL_HOST_PASSWORD`               | The password to use when connecting to the SMTP server | `` |
| `EMAIL_PORT`                        | The port to use when connecting to the SMTP Server | `587` |
| `EMAIL_USE_TLS`                     | Whether to use a TLS connection when talking to the SMTP server | `True` |
| `EMAIL_SUBJECT_PREFIX`              | Subject-line prefix for email messages sent | `` |
| `DEFAULT_FROM_EMAIL`                | The email address to be set in messages' FROM | `` |
| `DEFAULT_REPLYTO_EMAIL`             | The email address to be set in messages' REPLY TO | `` |

## Built With

* [Travis CI](https://travis-ci.org/) - Recommended CI/CD

## Contributing

Please read [CONTRIBUTING.md](https://github.com/buildlyio/docs/blob/master/CONTRIBUTING.md) for details on our code of conduct, and the process for submitting pull requests to us.

## Versioning

We use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/buildlyio/buildly-core/tags).

## Authors

* **Buildly** - *Initial work*

See also the list of [contributors](https://github.com/buildlyio/buildly-core/graphs/contributors) who participated in this project.

## License

This project is licensed under the GPL v3 License - see the [LICENSE](LICENSE) file for details.
