import re
import json
from . import mongo_api
from .dbmodels import Distributives, DistributivesRevisions
from flask import Response, request
from datetime import datetime
from mongoengine.errors import NotUniqueError, MultipleObjectsReturned, DoesNotExist
import logging
from copy import deepcopy
from packaging import version

_distr_mandatory_fields = ["citype", "version", "path", "checksum"]
_distr_search_fields = ["client"] + _distr_mandatory_fields
_revision_mandatory_fields = ["artifact_deliverable", "commentary"]
_revision_fields = ["revision", "timestamp"] + _revision_mandatory_fields

class DistributivesParentLoopError(Exception):
    def __init__ (self, distr_top, distr_to_check):
        super().__init__(f"""
        ===searching===:\n{distr_top.to_json()}\n
        ===found  in===:\n{distr_to_check.to_json()}
        """)

def response(code, data):
    return Response(
        status=code,
        mimetype="application/json",
        response=data
    )


def _distr_search_params(parms):
    """
    Filter dictionary for search parameters
    """
    if not parms:
        return parms

    # trick for None-type client value since MongoEngine requires a "not None" value for index
    # based on 'unique_with' constraint
    if "client" in parms and not parms.get("client"):
        parms["client"] = ""

    return dict((_key,parms.get(_key)) for _key in _distr_search_fields if _key in parms)

def _create_revision(distributive):
    """
    Create the distributive's revision
    :param distributive: Distributives object instance
    :return: DistributivesRevisions object
    """
    _revision = DistributivesRevisions()
    _revision.revision_of = distributive

    for _attr in _revision_fields:
        setattr(_revision, _attr, deepcopy(getattr(distributive, _attr)))

    return _revision

def _fix_distinct_search_params(params):
    """
    Fix the client-value-type index search params (if so)
    :param params: search parameters
    :type params: dict
    :return: fixed parameters
    """

    if any([
        "citype" in params.keys() and "version" not in params.keys(),
        "citype" not in params.keys() and "version" in params.keys()]):
        raise ValueError(f"Both 'citype' and 'version' must be specified: {params}")

    if all(["citype" in params.keys(), "version" in params.keys()]) and not params.get("client"):
        params["client"] = ""

    return params

def _resolve_parents(parents):
    """
    Resolve all parents given and return a list of corresponding Distributives() objects
    :param parents: parents
    :type parents: list of dictionaries
    """
    if not parents:
        return list()

    _result = list()


    for _parent in parents:
        # parents may be deleted already, but it is not the cause to ignore
        # so "is_actual" is dropped here
        try:
            _search_params = _fix_distinct_search_params(_distr_search_params(_parent))
        except ValueError as _e:
            logging.debug(f"Parent search error: {_parent}: Error {type(_e)}: {_e}")
            continue

        if "is_actual" in _search_params.keys():
            del(_search_params["is_actual"])

        if not len(_search_params.keys()):
            logging.debug(f"No relevant search keywords found for parent: {_parent}")
            continue

        try:
            _distr = Distributives.objects.get(**_search_params)
        except Exception as _e:
            # it is OK, skip this parent binding
            logging.debug(f"Parent not found: {_parent}: Error {type(_e)}: {_e}")
            continue

        if not _distr:
            logging.debug(f"Parent search gives nothing: {_parent}")
            continue

        logging.debug(f"Appending {_distr.to_json()}")
        _result.append(_distr)

    return list(set(_result))

def _check_parent_loop(distr_to_check, distr_top=None):
    """
    Check if we have looped parents
    :param distr_to_check: distr to check
    :type distr_to_check: Distributives
    :param distr_top: top-level distributive
    :type distr_top: Distributives
    """

    if not distr_top:
        distr_top = distr_to_check

    for _parent in distr_to_check.parent:
        # check equality by primary key 
        # since some changes in other fields 
        # may be not written to database yet
        if all([_parent.citype == distr_top.citype,
                _parent.version == distr_top.version,
                _parent.client == distr_top.client]):
            raise DistributivesParentLoopError(_parent, distr_top)

        _check_parent_loop(_parent, distr_top)

def _distrs_list_for_json(distrs, count=None):
    """
    Carefully and recursively convert a distributives or revisions set
    to output JSON for returning to requestor.
    Need this since 'parent' and 'revision_of' are returned as {"$oid": "_hash_"}
    This is useless in external tools
    """
    _result = list()
    _attrs_to_convert = ["revision_of", "parent"]
    _counter = 0

    for _distr in distrs:
        _out = json.loads(_distr.to_json())

        for _attr in _attrs_to_convert:
            try:
                _value = getattr(_distr, _attr)
            except AttributeError as _e:
                logging.debug(f"Atrribute search error for {_distr.to_json()}: {_attr}")
                continue

            _is_list = isinstance(_value, list)

            if _is_list:
                _out[_attr] = list()
            else:
                _value = [_value]

            for _sub in _value:
                _sub_out = dict((_key, getattr(_sub, _key)) for _key in _distr_search_fields)

                if not _is_list:
                    _out[_attr] = _sub_out
                    break

                _out[_attr].append(_sub_out)

        _result.append(_out)

        if count:
            _counter += 1

            if _counter > count:
                break

    return _result

@mongo_api.route('/add_distributive', methods=['POST'])
def add_distributive():
    """
    Add a new distributive to DB
    """
    if not request.json:
        return response(400, "No data provided")

    logging.debug(f"Received a new distributive addition request: {request.json}")

    # check mandatory fields
    for _field in _distr_mandatory_fields:
        if not request.json.get(_field):
            logging.error(f"Mandatory field missing: {_field}. Returning 400")
            return response(400, f"'{_field}' is mandatory")

    # check other fields format
    _parents = request.json.get("parent")

    if _parents and not isinstance(_parents, list):
        logging.error(f"'parent' parameter is not a list: {type(_parents)}. Returning 400")
        return response(400, "'parent' is not list")

    # get current one if in database already
    _citype = request.json.get("citype")
    _version = request.json.get("version")
    _client = request.json.get("client", "")
    _revision = None
    _distr = None

    logging.debug(f"Search parameters: {_citype}:{_version}:{_client}")

    try:
        _distr = Distributives.objects.get(citype=_citype, version=_version, client=_client)
        logging.debug(f"Found distributive: {_distr.to_json()}")

        if _distr.is_actual:
            logging.info("Distributive is actual. Returning 409")
            return response(409, f"Already exists: '{_citype}:{_version}:{_client}'")

        logging.debug(f"Deleted distributive found for {_citype}:{_version}:{_client}. Creating a new revision.")
        _revision = _create_revision(_distr)
        _distr.revision += 1
    except DoesNotExist:
        logging.debug(f"No distributive found for {_citype}:{_version}:{_client}, creating new one")
        _distr = Distributives()
        _distr.citype = _citype
        _distr.version = _version
        _distr.client = _client
    except MultipleObjectsReturned:
        logging.error(f"Multiple found: {_citype}:{_version}:{_client}. Returning 409")
        return response(409, f"Already exists many times: {_citype}:{_version}:{_client}")
    except Exception as _e:
        logging.error(f"Search error for {_citype}:{_version}:{_client}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error {_citype}:{_version}:{_client}: {type(_e)}: {_e}")

    _distr.timestamp = datetime.now()

    # set all fields as it is done for the first time
    _distr.path = [request.json.get("path")]
    _distr.checksum = [request.json.get("checksum")]
    _distr.parent = _resolve_parents(_parents)

    try:
        _check_parent_loop(_distr)
    except DistributivesParentLoopError as _e:
        logging.error(f"Parent loop found: {type(_e)}: {_e}")
        return response(409, f"Parent loop found: {type(_e)}: {_e}")

    _distr.artifact_deliverable = request.json.get("artifact_deliverable", True)
    _distr.commentary = request.json.get("commentary", "Initial addition to DB")
    _distr.is_actual = True

    try:
        _distr.save()
        logging.debug(f"Successfully saved: {_distr.to_json()}")
    except NotUniqueError as _e:
        logging.error(f"Saving failed {_distr.to_json()}: {type(_e)}: {_e}. Returning 409")
        return response(409, f"Already exists: {_citype}:{_version}:{_client}, Error {type(_e)}: {_e}")
    except Exception as _e:
        logging.error(f"Saving failed {_distr.to_json()}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Adding error {type(_e)}: {_e}")

    # now save a revision if our distributive was saved successfuly
    if _revision:
        logging.debug(f"Saving revision: {_revision.to_json()}")
        _revision.save()

    return response(201, _distr.to_json())

@mongo_api.route('/update_distributive', methods=['POST'])
def update_distributive():
    """
    Update existing distributive in DB
    """
    logging.info(f"Received an update request: {request.json}")

    # Check te request. If  no changes specified - then nothing to do
    if not request.json:
        logging.error("No data provided. Returning 400")
        return response(400, "No data provided")

    _changes = request.json.get("changes")

    if not isinstance(_changes, dict):
        logging.error(f"'changes' should be a dictionary, got: {type(_changes)}. Returning 400.")
        return response(400, f"'changes' should be a dictionary, not {type(_changes)}")

    if not _changes:
        logging.error("No changes in the request. Returning 400")
        return response(400, "'changes' are mandatory")

    logging.debug(f"Changes requested: {_changes}")

    # check other fields format
    _parents = _changes.get("parent")

    if _parents and not isinstance(_parents, list):
        logging.error(f"'parent' parameter is not a list: {type(_parents)}. Returning 400")
        return response(400, "'changes.parent' is not list")

    # we may ask to update by one of keys:
    # GAV (path), checksum, citype-version pair
    # surely caller have to know what it is asking
    try:
        _search_params = _fix_distinct_search_params(_distr_search_params(request.json))
    except ValueError as _e:
        logging.error(f"Search error {request.json}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error: {request.json}, Error {type(_e)}: {_e}")

    _search_params["is_actual"] = True

    logging.debug(f"Search params: {_search_params}")

    try:
        _distr = Distributives.objects.get(**_search_params)
    except DoesNotExist:
        logging.error(f"Not found: {_search_params}. Returning 404")
        return response(404, f"Not found: {_search_params}")
    except MultipleObjectsReturned:
        logging.error(f"Multiple found: {_search_params}. Returning 409")
        return response(409, f"Exists many times: {_search_params}")
    except Exception as _e:
        logging.error(f"Search error: {_search_params}: {type(_e)}:{_e}. Returning 400")
        return response(400, f"Search error: {_search_params}: {type(_e)}: {_e}")

    logging.debug(f"Found distributive: {_distr.to_json()}")

    # we have to process fields individually
    # we have to deny 'is_actual' external change
    # we have to deny primary key (citype-version-client trier) change also
    _artifact_deliverable = _changes.get("artifact_deliverable")
    _comment = _changes.get("commentary")
    _changes_detected = False
    _revision = None

    logging.debug("Looking for append fields in 'changes'")
    for _append_field in ["path", "checksum"]:
        _append_value = _changes.get(_append_field)

        if not _append_value:
            # do nothing if nothing asked
            continue

        logging.debug(f"Found '{_append_field}'")
        _current_value = getattr(_distr, _append_field)
        logging.debug(f"Current value: {_current_value}")

        if _append_value in _current_value:
            continue

        _changes_detected = True
        logging.debug(f"Appending new value: '{_append_value}'")
        _current_value.append(_append_value)
        setattr(_distr, _append_field, _current_value)

    ### special cases
    # parent
    # for current concept we make full replacement of parents
    if _parents:
        logging.debug("Parents replacement requested")
        _changes_detected = True
        _distr.parent = _resolve_parents(_parents)

        try:
            _check_parent_loop(_distr)
        except DistributivesParentLoopError as _e:
            logging.error(f"Parent loop detected: {type(_e)}: {_e}")
            return response(409, f"Parent loop found: {type(_e)}: {_e}")

    # deliverable
    # it have to be not 'None', but may be 'False', so simply 'if _artifact_deliverable' is not applicable here
    if _artifact_deliverable is not None and _artifact_deliverable != _distr.artifact_deliverable:
        logging.debug(f"Requested update 'artifact_deliverable'")

        # We are denying changes for this flag without a commentary
        if not _comment:
            logging.error("'artifact_deliverable' changed, but 'commentary' was not provided")
            return response (400, "Deliverable flag can not be changed without a commentary")

        _changes_detected = True
        _revision = _create_revision(_distr)
        _distr.artifact_deliverable = _artifact_deliverable
        logging.debug(f"Deliverable flag updated: {_artifact_deliverable}")

    # replace comment if new one given
    if _comment and _comment != _distr.commentary:
        _changes_detected = True

        if not _revision:
            _revision = _create_revision(_distr)

        _distr.commentary = _comment
        logging.debug(f"Commentary updated: '{_comment}'")

    # return OK if no changes detected
    if not _changes_detected:
        logging.debug("No changes detected, returning 200")
        return response(200, _distr.to_json())

    # save revision if needed only
    if _revision:
        _distr.revision += 1
        _distr.timestamp = datetime.now()
        logging.debug(f"New revision value: {_distr.revision}. Timestamp: {_distr.timestamp}")

    # return error in case of conflict
    try:
        _distr.save()
    except NotUniqueError:
        logging.error(f"Existing distributive found: {_distr.to_json()}. Returning 409")
        return response(409, f"Already assigned to another distributive: {_distr.to_json()}'")

    # Saving current state of the document to Revisions collection
    # It should be done only if the current distributive update above was successfull
    if _revision:
        _revision.save()
        logging.debug(f"Revision saved: {_revision.revision}")

    logging.debug("Changes saved. Returning 201")
    return response(201, _distr.to_json())

@mongo_api.route('/delete_distributive', methods=['DELETE'])
def delete_distributive():
    """
    Delete specific distributive from DB
    """
    # we may ask deletion by one of keys:
    # GAV (path), citype-version-client trier
    # checksum deletion is not (yet?) supported
    # surely caller have to know what it is asking

    # Check te request. If nothing specified - then nothing to do
    if not request.json:
        return response(400, "No data provided")

    logging.debug(f"Received deletion request: {request.json}")

    # bad unsupported deletion fields
    for _key in ["checksum"]:
        if request.json.get(_key):
            logging.error(f"Unsupported key: {_key}. Returning 400")
            return response(400, f"Unsupported key: '{_key}'")

    # fix search parameters
    try:
        _search_params = _fix_distinct_search_params(_distr_search_params(request.json))
    except ValueError as _e:
        logging.error(f"Search error: '{request.json}': {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error: {request.json}: {type(_e)}: {_e}")

    _search_params["is_actual"] = True
    logging.debug(f"Search params: {_search_params}")

    try:
        _distr = Distributives.objects.get(**_search_params)
    except DoesNotExist:
        logging.debug(f"Not found: {_search_params}. Returning 200")
        return response(200, json.dumps(_search_params))
    except MultipleObjectsReturned:
        logging.error(f"Multiple found: {_search_params}. Returning 409")
        return response(409, f"Exists many times: {_search_params}")
    except Exception as _e:
        logging.error(f"Search error for {_serach_params}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error: {_search_params}: {type(_e)}: {_e}")

    # if we have 'path' as argument - perform full deletion if the path is last only
    _path = _search_params.get("path")
    if _path and _path in _distr.path:
        _distr.path.remove(_path)
    else:
        # delete all paths
        _distr.path = list()

    if not _distr.path:
        _distr.is_actual = False

    # here we do not want do catch an exception sicne we are removing values only
    logging.debug(f"Marking inactual: {_distr.to_json()}. Returning 200")
    _distr.save()
    return response(200, _distr.to_json())

@mongo_api.route('/get_distributives', methods=['GET'])
def get_distributives():
    """
    Get specific distributive from DB
    """

    _search_params = dict()
    _count = None

    # check 'artifact_deliverable' value
    if request.json:
        _search_params = _distr_search_params(request.json)
        _artifact_deliverable = request.json.get("artifact_deliverable")

        if _artifact_deliverable is not None:
            if not isinstance(_artifact_deliverable, bool):
                logging.error(f"Incorrect type for 'artifact_deliverable': {type(_artifact_deliverable)}. Returning 400")
                return response(400, f"Incorrect type for 'artifact_deliverable': {type(_artifact_deliverable)}")

            _search_params["artifact_deliverable"] = _artifact_deliverable

        _count = request.json.get("count")

    _search_params["is_actual"] = True

    return response(200, json.dumps(_distrs_list_for_json(Distributives.objects(**_search_params), _count)))

@mongo_api.route('/get_distributive_revisions', methods=['GET'])
def get_distributive_revisions():
    """
    Get all revisions for the distributive
    """
    # Check te request. If nothing specified - then nothing to do
    if not request.json:
        return response(400, "No data provided")

    try:
        _search_params = _fix_distinct_search_params(_distr_search_params(request.json))
    except ValueError as _e:
        logging.error(f"Search error: {request.json}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error: {request.json}: {type(_e)}: {_e}")

    _search_params["is_actual"] = True

    logging.debug(f"Search params: {_search_params}")

    try:
        _distr = Distributives.objects.get(**_search_params)
    except DoesNotExist:
        logging.error(f"Not found: {_search_params}. Returning 404")
        return response(404, f"Not found: {_search_params}")
    except MultipleObjectsReturned:
        logging.error(f"Multiple found: {_search_params}. Returning 409")
        return response(409, f"Exists many times: {_search_params}")
    except Exception as _e:
        logging.error(f"Search error: {_search_params}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error: {_search_params}: {type(_e)}: {_e}")

    _revisions = DistributivesRevisions.objects(revision_of=_distr).order_by('-timestamp')

    # Appending the current state to the beginning of the list
    # seems converting to list is the only correct way to produce final JSON
    # because objects of type Distributives are not JSON-serializable

    return response(200, json.dumps(
        list(map(lambda x: json.loads(x.to_json()), [_create_revision(_distr)] + list(_revisions)))))

@mongo_api.route('/get_versions_by_citype', methods=['GET'])
def get_versions_by_citype():
    """
    Get all versions by citype
    No sorting applied, it is a task of a requestor
    """
    if not request.json:
         return response(400, "'citype' is mandatory")

    _citype = request.json.get("citype")
    _artifact_deliverable = request.json.get("artifact_deliverable")
    _client = request.json.get("client")

    # we have to provide enabled parents even if binary distributive has been deleted from repo
    #_search_params = {"is_actual": True}
    _search_params = {}

    if not _citype:
         return response(400, "'citype' is mandatory")

    _search_params["citype"] = _citype

    if not _client:
        _client = ""

    _search_params["client"] = _client


    if _artifact_deliverable is not None:
        if not isinstance(_artifact_deliverable, bool):
            logging.error(f"Incorrect type for 'artifact_deliverable': {type(_artifact_deliverable)}. Returning 400")
            return response(400, f"Incorrect type for 'artifact_deliverable': {type(_artifact_deliverable)}")

        _search_params["artifact_deliverable"] = _artifact_deliverable

    logging.debug(f"Search params: {_search_params}")

    _versions_list = Distributives.objects(**_search_params).distinct(field="version")
    return response(200, json.dumps(_versions_list))

@mongo_api.route('/artifact_deliverable', methods=['GET'])
def check_artifact_deliverable():
    """
    Check artifact_deliverable
    """
    # Check te request. If nothing specified - then nothing to do
    if not request.json:
        return response(400, "No data provided")

    try:
        _search_params = _fix_distinct_search_params(_distr_search_params(request.json))
    except ValueError as _e:
        logging.error(f"Search error {request.json}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error: {request.json}: {type(_e)}: {_e}")

    # we have to deny deleted distributives also if they were denied before being deleted
    #_search_params["is_actual"] = True

    # returning default 'True' in case of known exceptions

    logging.debug(f"Search params: {_search_params}")

    try:
        _distr = Distributives.objects.get(**_search_params)
    except (DoesNotExist, MultipleObjectsReturned):
        return response(200, json.dumps([True]))
    except Exception as _e:
        logging.error(f"Search error: {_search_params}: {type(_e)}: {_e}. Returning 400")
        return response(400, f"Search error: {_search_params}: {type(_e)}: {_e}")

    return response(200, json.dumps([all(list(map(lambda x: x.artifact_deliverable, [_distr] + _distr.parent)))]))

@mongo_api.route('/versions_by_citype/<path:_version_state>', methods=['GET'])
def versions_by_citype(_version_state=None):
    """
    Get all versions by citype
    Sorting applied
    """
    return_response_status = 200
    _search_params = dict()
    out_values = list()
    return_json = {"values": out_values }
    ci_types_lists = request.args.getlist("ci_type")

    if _version_state not in ['latest', 'all']:
        return_json = {"values": [],
                       "error": f"No version for {_version_state} found. Try 'all' or 'latest'."}
        return response(404, json.dumps(return_json))

    if not ci_types_lists:
        return_json = {"values": [], "error": "No CI type specified in request"}
        return response(400, json.dumps(return_json))

    clean_ci_types_lists = list(dict.fromkeys(ci_types_lists))
    logging.debug(f"{clean_ci_types_lists}")

    for _each_citype in clean_ci_types_lists:
        _search_params["citype"] = _each_citype
        _versions_list = Distributives.objects(**_search_params)
        _out_values = list()

        if not _versions_list:
            continue

        for _each_ci_type_object in _versions_list:
            _sorted_paths = deepcopy(_each_ci_type_object.path)
            _sorted_checksum = deepcopy(_each_ci_type_object.checksum)
            _sorted_paths.sort()
            _sorted_checksum.sort()
            _dict = {"ci_type": _each_citype,
                    "paths": deepcopy(_sorted_paths),
                    "checksums": deepcopy(_sorted_checksum),
                    "version": _each_ci_type_object.version
                    }
            _out_values.append(_dict)

        if not _out_values:
            continue

        if _version_state == 'latest':
            _out_values.sort(key=lambda x: version.parse(x.get("version")))
            out_values.append(_out_values.pop())
        else:
            out_values.extend(_out_values)

    if not out_values:
        return_json = { "values": [],
                        "error": "No version data found"}
        return response(404, json.dumps(return_json))

    return_json = {"values": out_values }
    return response(return_response_status, json.dumps(return_json))
