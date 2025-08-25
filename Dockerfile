FROM python:3.11-alpine

# Do not buffer log messages in memory; some messages can be lost otherwise
ENV PYTHONUNBUFFERED 1

RUN apk update

WORKDIR /code

RUN apk add --no-cache postgresql-libs bash openldap-dev &&\
    apk add --no-cache --virtual .build-deps gcc musl-dev postgresql-dev libffi-dev

COPY ./requirements/base.txt requirements/base.txt
COPY ./requirements/production.txt requirements/production.txt
RUN pip install --upgrade pip && pip install -r requirements/production.txt --no-cache-dir

ADD . /code

# Collecting static files
RUN ./scripts/collectstatic.sh

RUN apk del .build-deps

# Specify tag name to be created on github
LABEL version="1.5.8"

EXPOSE 8080
ENTRYPOINT ["bash", "/code/scripts/docker-entrypoint.sh"]
