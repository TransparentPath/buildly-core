import json
from datamesh.models import JoinRecord, Relationship, LogicModuleModel
from core.models import LogicModule


def gateway_custodian_relationship():
    """
     gateway <-> custodian - different service model join.
     Load gateway with custodian_uuid from json file and write the data directly into the JoinRecords.
     open json file from data directory in root path.
    """

    model_json_file = "gateway.json"

    # load json file and take data into model_data variable
    with open(model_json_file, 'r', encoding='utf-8') as model_data:
        model_data = json.load(model_data)

    # get logic module from core
    origin_logic_module = LogicModule.objects.get(endpoint_name='custodian')
    related_logic_module = LogicModule.objects.get(endpoint_name='sensors')

    # get or create datamesh Logic Module Model
    related_model, _ = LogicModuleModel.objects.get_or_create(
        model='Gateway',
        logic_module_endpoint_name=origin_logic_module.endpoint_name,
        endpoint='/gateway/',
        lookup_field_name='id',
    )

    # get or create datamesh Logic Module Model
    origin_model, _ = LogicModuleModel.objects.get_or_create(
        model='Custodian',
        logic_module_endpoint_name=related_logic_module.endpoint_name,
        endpoint='/custodian/',
        lookup_field_name='id',
    )

    # get or create relationship of origin_model and related_model in datamesh
    relationship, _ = Relationship.objects.get_or_create(
        origin_model=origin_model,
        related_model=related_model,
        key='custodian_gateway_relationship'
    )
    eligible_join_records = []
    counter = 0

    # iterate over loaded JSON data
    for data in model_data:

        counter += 1

        # get item ids from model data
        custodian_uuid = data['fields']['custodian_uuid']

        # check if shipment_uuid is null or not
        if not custodian_uuid:
            continue

        # create join record
        join_record, _ = JoinRecord.objects.get_or_create(
            relationship=relationship,
            record_id=data['pk'],
            related_record_uuid=custodian_uuid,
            defaults={'organization': None}
        )
        print(join_record)
        # append eligible join records
        eligible_join_records.append(join_record.pk)

    print(f'{counter} Gateway parsed and written to the JoinRecords.')

    # delete not eligible JoinRecords in this relationship
    deleted, _ = JoinRecord.objects.exclude(pk__in=eligible_join_records).filter(relationship=relationship).delete()
    print(f'{deleted} JoinRecord(s) deleted.')


def organization_gateway_relationship():
    """
     gateway <-> organization - with core <-> service model join.
     Load gateway with organization_uuid from json file and write the data directly into the JoinRecords.
     open json file from data directory in root path.
    """

    model_json_file = "shipments.json"

    # load json file and take data into model_data variable
    with open(model_json_file, 'r', encoding='utf-8') as file_data:
        model_data = json.load(file_data)

    # get logic module from core
    origin_model = LogicModule.objects.get(endpoint_name='sensors')

    # get or create datamesh Logic Module Model
    origin_model, _ = LogicModuleModel.objects.get_or_create(
        model='Gateway',
        logic_module_endpoint_name=origin_model.endpoint_name,
        endpoint='/gateway/',
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

    print(f'{counter} Gateway <-> Organization parsed and written to the JoinRecords.')

    # delete not eligible JoinRecords in this relationship
    deleted, _ = JoinRecord.objects.exclude(pk__in=eligible_join_records).filter(relationship=relationship).delete()
    print(f'{deleted} JoinRecord(s) deleted.')