from django.template.defaultfilters import slugify
from factory import SubFactory, Faker, LazyAttribute
from factory.django import DjangoModelFactory

from core.models import (
    CoreUser as CoreUserM,
    CoreGroup as CoreGroupM,
    LogicModule as LogicModuleM,
    Organization as OrganizationM,
)


class Organization(DjangoModelFactory):
    class Meta:
        model = OrganizationM
        django_get_or_create = ('name',)

    name = 'Default Organization'


class CoreGroup(DjangoModelFactory):

    name = Faker('name')

    class Meta:
        model = CoreGroupM


class CoreUser(DjangoModelFactory):
    class Meta:
        model = CoreUserM
        django_get_or_create = ('username',)

    organization = SubFactory(Organization)
    first_name = Faker('name')
    last_name = Faker('name')
    username = LazyAttribute(lambda o: slugify(o.first_name + '.' + o.last_name))
    email = LazyAttribute(lambda o: o.username + "@example.com")


class LogicModule(DjangoModelFactory):
    class Meta:
        model = LogicModuleM
        django_get_or_create = ('name',)

    name = 'products'
    endpoint = 'http://products.example.com/'
