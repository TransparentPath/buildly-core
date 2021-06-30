from django.conf import settings
import requests


datamesh_module_url = (settings.DATAMESH_URL + 'logicmodulemodels/')
datamesh_relationships_url = (settings.DATAMESH_URL + 'relationships/')
datamesh_join_url = (settings.DATAMESH_URL + 'joinrecords/')


model_url_endpoint = {'item': '/item/', 'product': '/product/', 'shipment': '/shipment/',
                      'producttype': '/product_type/', 'itemtype': '/item_type/',
                      'unitofmeasure': '/unit_of_measure/',
                      'gateway': '/gateway', 'sensor': '/sensors', 'sensorreport': '/sensor_report/',
                      'qrcode': '/qrcode/', 'aggregatereport': '/aggregate_report/',
                      'sensortype': '/sensor_type/', 'gatewaytype': '/gateway_type/',
                      'sensorreportalert': '/sensor_report_alert/',
                      'certification': '/certification/', 'custodiantype': '/custodian_type/',
                      'certificationtype': '/certification_type/', 'customeraccount': '/customer_account/',
                      'subscriptiontype': '/subscription_type/', 'custody': 'Custody', 'custodian': 'Custodian'
                      }


def payload_model(service_name, model):
    # create a paylaod for post request of logic module model
    # model_name = model.lower()  # Convert input string for model name into lower case
    endpoint = model_url_endpoint.get(model.lower())
    payload = {
            "logic_module_endpoint_name": service_name,
            "model": str(model),
            # "endpoint": "/"+str(endpoint)+"/",
            "endpoint": endpoint,
            "lookup_field_name": "id",
            "is_local": False
        }
    return payload


logic_module_model = {'shipment': ['Item', 'Product', 'Shipment', 'ProductType', 'ItemType', 'UnitOfMeasure'],
                      'sensors': ['Gateway', 'Sensor', 'SensorReport', 'QRCode',
                                  'AggregateReport', 'SensorReportAlert', 'SensorType', 'GatewayType'],
                      'custodian': ['Certification', 'Custody', 'Custodian', 'Contact', 'CustodianType',
                                    'CertificationType', 'CustomerAccount', 'SubscriptionType']
                      }


def create_module_model():
    # It will create logic module model for model defined in logic_module_model dict object
    # If logic module model for that service already present, It will not create for the same.
    for service_name, module_models in logic_module_model.items():
        # Create a payload for logic module model
        for model in module_models:
            payload = payload_model(service_name, model)
            # Send a post request with payload to create logic module  model
            requests.post(datamesh_module_url,
                          json=payload,
                          headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},
                          )


def module_model_uuid():
    # It will store logic module model uuid in dict which will needed for creating relationship
    module_model_uuid = {}
    # Get all logic module model registered in datamesh
    datamesh_modules = requests.get(datamesh_module_url,
                                    headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},).json()
    # Store logic module model uuid as value nad logic module model name as key
    for datamesh_module in datamesh_modules:
        module_model_uuid[datamesh_module.get("model").lower()] = datamesh_module.get("logic_module_model_uuid")
    return module_model_uuid


def model_relationship_payload(origin_model_uuid, related_model_uuid, origin_name, related_name):
    # Payload for creating relationship
    relationship_payload = {
            "origin_model_id": origin_model_uuid,
            "related_model_id": related_model_uuid,
            "key": origin_name+"_"+related_name+"_"+"relationship"
        }
    return relationship_payload


def create_relationship_model(origin_model, related_model):
    # Send post request to create relationship model
    uuid = module_model_uuid()   # Get uuid of respective model
    payload = model_relationship_payload(uuid.get(origin_model.lower()),
                                         uuid.get(related_model.lower()),
                                         origin_model.lower(), related_model.lower())
    requests.post(datamesh_relationships_url,
                  json=payload,
                  headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},
                  )


def join_record_payload(service_name, model_name,
                        related_service_name, related_model_name,
                        record_id_or_uuid, related_record_id_or_uuid):
    # model name should be as "shipmentShipment", where "shipment" is service and "Shipment" is model name
    # Join can be on base of id or uuid, so different payload for both
    if isinstance(record_id_or_uuid, int) and isinstance(related_record_id_or_uuid, int):
        record_payload = {"origin_model_name": service_name.lower()+model_name,
                          "related_model_name": related_service_name.lower()+related_model_name,
                          "record_id": record_id_or_uuid,
                          "related_record_id": record_id_or_uuid
                          }
    else:
        record_payload = {"origin_model_name": service_name.lower()+model_name,
                          "related_model_name": related_service_name.lower()+related_model_name,
                          "record_uuid": record_id_or_uuid,
                          "related_record_uuid": record_id_or_uuid
                          }
    return record_payload


def create_join_records(service_name, model_name,
                        related_service_name, related_model_name,
                        record_id_or_uuid, related_record_id_or_uuid):
    # It create join record. Input module should be already registered on datamesh logic module model
    # It also create relationship if relationship of model is not present
    payload = join_record_payload(service_name, model_name,
                                  related_service_name, related_model_name,
                                  record_id_or_uuid, related_record_id_or_uuid)
    requests.post(datamesh_join_url,
                  json=payload,
                  headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},
                  )
# To create logic model
# create_module_model()
# To create relationship
# create_relationship_model('custody','item')
# Tp create join, it will create relationship as well if its not present
# create_join_records("custodian","Custodian","shipment","Shipment",1,2)
