import json
from datamesh.models import JoinRecord, Relationship, LogicModuleModel
from core.models import LogicModule, Organization
import re


def shipment_gateway_relationship():
    """
     shipment <-> gateway - different service model join.
     Load shipment with gateway_uuid from json file and write the data directly into the JoinRecords.
     open json file from data directory in root path.
    """

    model_json_file = "shipments.json"

    # load json file and take data into model_data variable
    with open(model_json_file, 'r', encoding='utf-8') as model_data:
        model_data = json.load(model_data)

    # get logic module from core
    origin_logic_module = LogicModule.objects.get(endpoint_name='shipment')
    related_logic_module = LogicModule.objects.get(endpoint_name='sensors')

    # get or create datamesh Logic Module Model
    related_model, _ = LogicModuleModel.objects.get_or_create(
        model='Gateway',
        logic_module_endpoint_name=related_logic_module.endpoint_name,
        endpoint='/gateway/',
        lookup_field_name='id',
    )

    # get or create datamesh Logic Module Model
    origin_model, _ = LogicModuleModel.objects.get_or_create(
        model='Shipment',
        logic_module_endpoint_name=origin_logic_module.endpoint_name,
        endpoint='/shipment/',
        lookup_field_name='id',

    )

    # get or create relationship of origin_model and related_model in datamesh
    relationship, _ = Relationship.objects.get_or_create(
        origin_model=origin_model,
        related_model=related_model,
        key='shipment_gateway_relationship'
    )
    eligible_join_records = []
    counter = 0

    # iterate over loaded JSON data
    for data in model_data:

        counter += 1

        # get item ids from model data
        gateway_uuid = data['fields']['gateway_ids']
        # check if shipment_uuid is null or not
        if not gateway_uuid:
            continue

        # convert uuid string to list
        gateway_uuid_list = re.findall(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){4}[0-9a-f]{8}', gateway_uuid)

        for gateway_uuid in gateway_uuid_list:
            # get uuid from string
            # create join record
            join_record, _ = JoinRecord.objects.get_or_create(
                relationship=relationship,
                record_id=data['pk'],
                related_record_uuid=gateway_uuid,
                defaults={'organization': None}
            )
            print(join_record)
            # append eligible join records
            eligible_join_records.append(join_record.pk)

    print(f'{counter} shipment <-> gateway parsed and written to the JoinRecords.')

    # delete not eligible JoinRecords in this relationship
    deleted, _ = JoinRecord.objects.exclude(pk__in=eligible_join_records).filter(relationship=relationship).delete()
    print(f'{deleted} JoinRecord(s) deleted.')


def shipment_item_relationship():
    """
     shipment <-> gateway - within service model join.
     Load shipment with item_id from json file and write the data directly into the JoinRecords.
     open json file from data directory in root path.
    """

    model_json_file = "shipments.json"

    # load json file and take data into model_data variable
    with open(model_json_file, 'r', encoding='utf-8') as file_data:
        model_data = json.load(file_data)

    # get logic module from core
    origin_logic_module = LogicModule.objects.get(endpoint_name='shipment')
    related_logic_module = LogicModule.objects.get(endpoint_name='shipment')

    # get or create datamesh Logic Module Model
    origin_model, _ = LogicModuleModel.objects.get_or_create(
        model='Shipment',
        logic_module_endpoint_name=related_logic_module.endpoint_name,
        endpoint='/shipment/',
        lookup_field_name='id',

    )

    # get or create datamesh Logic Module Model
    related_model, _ = LogicModuleModel.objects.get_or_create(
        model='Item',
        logic_module_endpoint_name=origin_logic_module.endpoint_name,
        endpoint='/item/',
        lookup_field_name='id',

    )

    # get or create relationship of origin_model and related_model in datamesh
    relationship, _ = Relationship.objects.get_or_create(
        origin_model=origin_model,
        related_model=related_model,
        key='shipment_item_relationship'
    )
    eligible_join_records = []
    counter = 0

    # iterate over loaded JSON data
    for related_data in model_data:

        counter += 1

        item_ids = related_data['fields']['items']

        if not item_ids:
            continue
        # iterate over item_ids
        for item_id in item_ids:
            join_record, _ = JoinRecord.objects.get_or_create(
                relationship=relationship,
                record_id=related_data['pk'],
                related_record_id=item_id,
                defaults={'organization': None}
            )
            print(join_record)
            eligible_join_records.append(join_record.pk)

    print(f'{counter} Shipment parsed and written to the JoinRecords.')

    # delete not eligible JoinRecords in this relationship
    deleted, _ = JoinRecord.objects.exclude(pk__in=eligible_join_records).filter(relationship=relationship).delete()
    print(f'{deleted} JoinRecord(s) deleted.')


def consortium_shipment_relationship():
    """
     shipment <-> consortium - with core <-> service model join.
     Load shipment with consortium_uuid from json file and write the data directly into the JoinRecords.
     open json file from data directory in root path.
    """

    model_json_file = "shipments.json"

    # load json file and take data into model_data variable
    with open(model_json_file, 'r', encoding='utf-8') as file_data:
        model_data = json.load(file_data)

    # get logic module from core
    origin_model = LogicModule.objects.get(endpoint_name='shipment')

    """ for core logic_module_endpoint_name will be "core" """

    # get or create datamesh Logic Module Model
    origin_model, _ = LogicModuleModel.objects.get_or_create(
        model='Shipment',
        logic_module_endpoint_name=origin_model.endpoint_name,
        endpoint='/shipment/',
        lookup_field_name='id',
    )
    # get or create datamesh Logic Module Model
    related_model, _ = LogicModuleModel.objects.get_or_create(
        model='Consortium',
        logic_module_endpoint_name="core",
        endpoint='/consortium/',
        lookup_field_name='consortium_uuid',
        is_local=True,
    )

    # get or create relationship of origin_model and related_model in datamesh
    relationship, _ = Relationship.objects.get_or_create(
        origin_model=origin_model,
        related_model=related_model,
        key='shipment_consortium_relationship'
    )
    eligible_join_records = []
    counter = 0

    # iterate over loaded JSON data
    for related_data in model_data:

        counter += 1

        # get consortium_uuid
        consortium_uuid = related_data['fields']['consortium_uuid']

        if not consortium_uuid:
            continue

        # create join record
        join_record, _ = JoinRecord.objects.get_or_create(
            relationship=relationship,
            record_id=related_data['pk'],
            related_record_uuid=consortium_uuid,
            defaults={'organization': None}
        )
        print(join_record)
        eligible_join_records.append(join_record.pk)

    print(f'{counter} shipment <-> consortium parsed and written to the JoinRecords.')

    # delete not eligible JoinRecords in this relationship
    deleted, _ = JoinRecord.objects.exclude(pk__in=eligible_join_records).filter(relationship=relationship).delete()
    print(f'{deleted} JoinRecord(s) deleted.')


def organization_shipment_relationship():
    """
     shipment <-> organization - with core <-> service model join.
     Load shipment with organization_uuid from json file and write the data directly into the JoinRecords.
     open json file from data directory in root path.
    """

    model_json_file = "shipments.json"

    # load json file and take data into model_data variable
    with open(model_json_file, 'r', encoding='utf-8') as file_data:
        model_data = json.load(file_data)

    # get logic module from core
    origin_model = LogicModule.objects.get(endpoint_name='shipment')

    # get or create datamesh Logic Module Model
    origin_model, _ = LogicModuleModel.objects.get_or_create(
        model='Shipment',
        logic_module_endpoint_name=origin_model.endpoint_name,
        endpoint='/shipment/',
        lookup_field_name='id',
    )

    """ for core logic_module_endpoint_name will be "core" and is_local=True """

    # get or create datamesh Logic Module Model
    related_model, _ = LogicModuleModel.objects.get_or_create(
        model='Organization',
        logic_module_endpoint_name="core",
        endpoint='/organization/',
        lookup_field_name='organization_uuid',
        is_local=True,
    )

    # get or create relationship of origin_model and related_model in datamesh
    relationship, _ = Relationship.objects.get_or_create(
        origin_model=origin_model,
        related_model=related_model,
        key='shipment_organization_relationship'
    )
    eligible_join_records = []
    counter = 0

    # iterate over loaded JSON data
    for related_data in model_data:

        counter += 1

        # get consortium_uuid
        organization_uuid = related_data['fields']['organization_uuid']

        if not organization_uuid:
            continue

        # create join record
        join_record, _ = JoinRecord.objects.get_or_create(
            relationship=relationship,
            record_id=related_data['pk'],
            related_record_uuid=organization_uuid,
            defaults={'organization': None}
        )
        print(join_record)
        eligible_join_records.append(join_record.pk)

    print(f'{counter} Shipment <-> Organization parsed and written to the JoinRecords.')

    # delete not eligible JoinRecords in this relationship
    deleted, _ = JoinRecord.objects.exclude(pk__in=eligible_join_records).filter(relationship=relationship).delete()
    print(f'{deleted} JoinRecord(s) deleted.')
