from datetime import timedelta

from django.template.defaultfilters import slugify
from django.utils import timezone
from factory import SubFactory, Faker, LazyAttribute
from factory.django import DjangoModelFactory

from core.models import (
    CoreUser as CoreUserM,
    CoreGroup as CoreGroupM,
    Invitation as InvitationM,
    LogicModule as LogicModuleM,
    Organization as OrganizationM,
    PasswordResetCode as PasswordResetCodeM,
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


class PasswordResetCode(DjangoModelFactory):
    class Meta:
        model = PasswordResetCodeM

    user = SubFactory(CoreUser)
    code = '123456'
    expires_at = LazyAttribute(lambda o: timezone.now() + timedelta(minutes=15))


class Invitation(DjangoModelFactory):
    class Meta:
        model = InvitationM

    email = Faker('email')
    organization = SubFactory(Organization)
    user_role = 'Users'
    invited_by = SubFactory(CoreUser)
    expires_at = LazyAttribute(lambda o: timezone.now() + timedelta(hours=72))
    original_expires_at = LazyAttribute(lambda o: o.expires_at)
