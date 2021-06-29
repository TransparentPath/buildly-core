from django.conf import settings
import requests
import json


datamesh_module_url = (settings.DATAMESH_URL + 'logicmodulemodels/')
datamesh_relationships_url = (settings.DATAMESH_URL + 'relationships/')
datamesh_join_url = (settings.DATAMESH_URL + 'joinrecords/')

def payload_model(model):
    #create a paylaod for post request of logic module model
    endpoint=model.lower()  # Convert input string for model name into lower case
    payload = {
            "logic_module_endpoint_name": endpoint,
            "model":str(model),
            "endpoint": "/"+str(endpoint)+"/",
            "lookup_field_name": "id",
            "is_local":False
        }
    return payload

logic_module_model={'item':'Item','product':'Product','shipment':'Shipment',
                    'gateway':'Gateway','sensor':'Sensor','sensorreport':'SensorReport',
                    'qrcode':'QRCode','aggregatereport':'AggregateReport',
                    'sensorreportalert':'SensorReportAlert','certification':'Certification',
                    'custody':'Custody','custodian':'Custodian'
                    }

def create_module_model():
    # It will create logic module model for model defined in logic_module_model dict object
    # If logic module model for that service already present, It will not create for the same.
    for module_model in logic_module_model.values():
        # Create a payload for logic module model
        payload=payload_model(module_model)
        # Send a post request with payload to create logic module  model
        datamesh_module = requests.post(
                        datamesh_module_url,
                        json=payload,
                        headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},
                    )
        
def module_model_uuid():
    # It will store logic module model uuid in dict which will needed for creating relationship
    module_model_uuid={}
    # Get all logic module model registered in datamesh
    datamesh_modules = requests.get(
                    datamesh_module_url,
                    headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},
                ).json()
    # Store logic module model uuid as value nad logic module model name as key
    for datamesh_module in datamesh_modules:
        module_model_uuid[datamesh_module.get("model").lower()] = datamesh_module.get("logic_module_model_uuid")  
    return module_model_uuid  

def model_relationship_payload(origin_model_uuid,related_model_uuid, origin_name, related_name):
    # Payload for creating relationship
    relationship_payload= {
            "origin_model_id": origin_model_uuid,
            "related_model_id": related_model_uuid,
            "key": origin_name+"_"+related_name+"_"+"relationship"
        }
    return relationship_payload

def create_relationship_model(origin_model,related_model):
    # Send post request to create relationship model
    uuid = module_model_uuid()   # Get uuid of respective model
    payload=model_relationship_payload(uuid.get(origin_model.lower()),uuid.get(related_model.lower()),origin_model.lower(),related_model.lower())
    relationship_model = requests.post(
                    datamesh_relationships_url,
                    json=payload,
                    headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},
                )

def join_record_payload(service_name,model_name,related_service_name,related_model_name,record_id_or_uuid,related_record_id_or_uuid):
    # model name should be as "shipmentShipment", where "shipment" is service and "Shipment" is model name
    # Join can be on base of id or uuid, so different payload for both
    if isinstance(record_id_or_uuid,int) and isinstance(related_record_id_or_uuid,int):
        record_payload = {
                                "origin_model_name": service_name.lower()+model_name,
                                "related_model_name": related_service_name.lower()+related_model_name,
                                "record_id": record_id_or_uuid,
                                "related_record_id": record_id_or_uuid
                              }
    else:
        record_payload = {
                                "origin_model_name": service_name.lower()+model_name,
                                "related_model_name": related_service_name.lower()+related_model_name,
                                "record_uuid": record_id_or_uuid,
                                "related_record_uuid": record_id_or_uuid
                              }
    return record_payload
                
def create_join_records(service_name,model_name,related_service_name,related_model_name,record_id_or_uuid,related_record_id_or_uuid):
    # It create join record. Input module should be already registered on datamesh logic module model
    # It also create relationship if relationship of model is not present 
    payload=join_record_payload(service_name,model_name,related_service_name,related_model_name,record_id_or_uuid,related_record_id_or_uuid)
    join_records = requests.post(
                    datamesh_join_url,
                    json=payload,
                    headers={'Authorization': 'Bearer ' + settings.CORE_AUTH_TOKEN},
                )
#create_relationship_model('custody','item')
#create_join_records("custodian","Custodian","shipment","Shipment",1,2)