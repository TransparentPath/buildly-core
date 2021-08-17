from django.core.management.base import BaseCommand
import json
from datamesh.models import JoinRecord, Relationship, LogicModuleModel
from core.models import LogicModule
from .gateway import gateway_custodian_relationship
from .shipment import shipment_gateway_relationship , consortium_shipment_relationship , shipment_item_relationship
from .custody import custody_shipment_relationship


class Command(BaseCommand):

    def add_arguments(self, parser):
        """Add --file argument to Command."""
        parser.add_argument(
            '--file', default=None, nargs='?', help='Path of file to import.',
        )

    def handle(self, *args, **options):
        run_seed(self, options['file'])


def run_seed(self, mode):
    """call function here."""

    """custody"""
    # custody shipment relationship
    custody_shipment_relationship()

    """gateway"""
    # gateway_custodian_relationship
    gateway_custodian_relationship()

    """shipment"""
    # custody_shipment_relationship
    shipment_gateway_relationship()
    consortium_shipment_relationship()
    shipment_item_relationship()


