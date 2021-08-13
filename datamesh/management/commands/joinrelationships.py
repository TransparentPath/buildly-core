from django.core.management.base import BaseCommand
import json
from datamesh.models import JoinRecord, Relationship, LogicModuleModel
from core.models import LogicModule


class Command(BaseCommand):

    def add_arguments(self, parser):
        """Add --file argument to Command."""
        parser.add_argument(
            '--file', default=None, nargs='?', help='Path of file to import.',
        )

    def handle(self, *args, **options):
        run_seed(self, options['file'])


def custody_shipment_relationship():
    """
     custody <-> shipment - different service model join.
     Load custody with shipment_uuid from json file and write the data directly into the JoinRecords.
     open json file from data directory in root path.
    """

    model_json_file = "custody.json"

    # load json file and take data into model_data variable
    with open(model_json_file, 'r', encoding='utf-8') as model_data:
        model_data = json.load(model_data)

    # get logic module from core
    origin_logic_module = LogicModule.objects.get(endpoint_name='shipment')
    related_logic_module = LogicModule.objects.get(endpoint_name='custodian')

    # get or create datamesh Logic Module Model
    # add lookup field as id or uuid
    origin_model, _ = LogicModuleModel.objects.get_or_create(
        model='Shipment',
        logic_module_endpoint_name=origin_logic_module.endpoint_name,
        endpoint='/shipment/',
        lookup_field_name='id',
    )

    # get or create datamesh Logic Module Model
    # add lookup field as id or uuid
    related_model, _ = LogicModuleModel.objects.get_or_create(
        model='Custody',
        logic_module_endpoint_name=related_logic_module.endpoint_name,
        endpoint='/custody/',
        lookup_field_name='id',
    )

    # get or create relationship of origin_model and related_model in datamesh
    relationship, _ = Relationship.objects.get_or_create(
        origin_model=origin_model,
        related_model=related_model,
        key='custody_shipment_relationship'
    )
    eligible_join_records = []
    counter = 0

    # iterate over loaded JSON data
    for data in model_data:

        counter += 1

        # get item ids from model data
        shipment_uuid = data['fields']['shipment_id']

        # check if shipment_uuid is null or not
        if not shipment_uuid:
            continue

        # create join record
        join_record, _ = JoinRecord.objects.get_or_create(
            relationship=relationship,
            record_uuid=shipment_uuid,
            related_record_id=data['pk'],
            defaults={'organization': None}
        )
        print(join_record)
        # append eligible join records
        eligible_join_records.append(join_record.pk)

    print(f'{counter} Contacts parsed and written to the JoinRecords.')

    # delete not eligible JoinRecords in this relationship
    deleted, _ = JoinRecord.objects.exclude(pk__in=eligible_join_records).filter(relationship=relationship).delete()
    print(f'{deleted} JoinRecord(s) deleted.')


def run_seed(self, mode):
    """call function here."""

    # custody shipment relationship
    custody_shipment_relationship()
