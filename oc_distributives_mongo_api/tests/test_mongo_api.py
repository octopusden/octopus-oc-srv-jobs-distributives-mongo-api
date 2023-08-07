import unittest
import json
from mongoengine import connect, disconnect
from ..app import create_app
from ..app.dbmodels import Distributives, DistributivesRevisions
from .config import UnitTestingConfig
from collections import namedtuple
from flask import Response
from ..app import routes
import hashlib
import os
import random
import posixpath
from copy import deepcopy

# trick for disabling logger output
import logging
logging.getLogger().disabled = True
logging.getLogger().propaagte = False

class MongoAPITest(unittest.TestCase):
    def setUp(self):
        app = create_app(UnitTestingConfig)
        with app.app_context():
            self.test_client = app.test_client()
        self.db = connect(
            os.getenv("MONGO_DB", "mongoenginetest"),
            host="mongodb://localhost",
            username=os.getenv("MONGO_USER", "test"),
            password=os.getenv("MONGO_PASSWORD", "test"),
            authentication_source="admin")

        DistributivesRevisions.objects.all().delete()
        Distributives.objects.all().delete()

    def tearDown(self):
        self.db.drop_database("mongoenginetest")
        disconnect()

    def _md5(self, content):
        hmd5 = hashlib.md5()
        hmd5.update(content.encode("utf8"))
        return hmd5.hexdigest()

    def _make_distr_json(self, arg, client=None, comment=None, citype=None):
        _citype = "TSTDSTR" if not citype else citype
        _version = f"{arg}.{arg}.{random.randint(0,99)}"
        _path = f"gg{arg}:aa{arg}:{_version}:pp{arg}"

        if client:
            _path = '.'.join([client, _path])

        _checksum = self._md5('$'.join([str(arg), _path, _citype, _version]))

        _result = {
            "path": _path,
            "citype": _citype,
            "version": _version,
            "checksum": _checksum}

        if client:
            _result["client"] = client

        return _result

    def _make_search_payload(self, dstr):
        _result = dict()

        for _attr in ["citype", "version", "client", "path", "checksum"]:
            if not dstr.get(_attr):
                continue

            _result[_attr] = dstr.get(_attr)

        return _result

    def _add_verify_distr(self, dstr):
        _citype = dstr.get("citype")
        _version = dstr.get("version")
        _path = dstr.get("path")
        _checksum = dstr.get("checksum")
        _client = dstr.get("client")

        if not _client:
            _client = ""

        self.assertIsNotNone(_citype)
        self.assertIsNotNone(_version)
        self.assertIsNotNone(_path)
        self.assertIsNotNone(_checksum)

        _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=dstr)
        self.assertEqual(_response.status_code, 201)

        _dbdstr = Distributives.objects.get(citype=_citype, version=_version, client=_client)
        self.assertEqual(_dbdstr.citype, _citype)
        self.assertEqual(_dbdstr.version, _version)
        self.assertEqual(_dbdstr.client, _client)
        self.assertTrue(_dbdstr.is_actual)
        self.assertEqual(_dbdstr.artifact_deliverable, dstr.get("artifact_deliverable", True))
        self.assertIsInstance(_dbdstr.parent, list)
        self.assertIsInstance(_dbdstr.path, list)
        self.assertTrue(_path in _dbdstr.path)
        self.assertTrue(_checksum in _dbdstr.checksum)
        self.assertEqual(_dbdstr.commentary, dstr.get("commentary", "Initial addition to DB"))
        return _dbdstr

    # Add distributive to clean database
    def test_add_to_clean_db(self):
        self.assertEqual(0, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())

        for _i in range(1, 3):
            client = f"TEST_CLIENT_{_i}"
            citype = f"TESTDSTR{_i}CLIENT"

            if not _i-1:
                # emulate standard distributive
                client = None

            _dbdstr = self._add_verify_distr(self._make_distr_json(_i, client=client, citype=citype))
            self.assertEqual(_i, Distributives.objects.count())
            self.assertEqual(0, DistributivesRevisions.objects.count())
            self.assertEqual(1, _dbdstr.revision)
            self.assertEqual(1, len(_dbdstr.path))
            self.assertEqual(1, len(_dbdstr.checksum))
            self.assertEqual(0, len(_dbdstr.parent))

    # Add existent distributive
    def test_add_existent(self):
        self.assertEqual(0, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())

        for _i in range(1, 3):
            client = f"TEST_CLIENT_{_i}"
            citype = f"TESTDSTR{_i}CLIENT"

            if not _i-1:
                # emulate standard distributive
                client = None

            _d = self._make_distr_json(_i, client=client, citype=citype)
            _dbdstr = self._add_verify_distr(_d)

            # add this once again
            _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=_d)
            self.assertEqual(_response.status_code, 409)
            self.assertEqual(_i, Distributives.objects.count())
            self.assertEqual(0, DistributivesRevisions.objects.count())

    # Add distributive - overwrite deleted
    def test_add_overwrite_deleted(self):
        for _i in range(1, 3):
            client = f"TEST_CLIENT_{_i}"
            _citype = f"TESTDSTR{_i}CLIENT"

            if not _i-1:
                # emulate standard distributive
                client = None

            _d = self._make_distr_json(_i, client=client, citype=_citype)
            _dbdstr = self._add_verify_distr(_d)
            _version = _d.get("version")

            #now delete it
            _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"),
                    json={"citype": _citype, "version": _version, "client": client})
            self.assertIn(_response.status_code, [200, 201])

            #now add it once again with another comment
            _d["commentary"] = f"Another comment {_i}, {client}"
            _dbdstr = self._add_verify_distr(_d)
            self.assertEqual(_i, Distributives.objects.count())

            #should be one reision for deletion and one for adding again
            self.assertEqual(2, _dbdstr.revision)
            self.assertEqual(1, len(_dbdstr.path))
            self.assertEqual(1, len(_dbdstr.checksum))
            self.assertEqual(0, len(_dbdstr.parent))
            self.assertEqual(_d.get("commentary"), _dbdstr.commentary)

            if client:
                self.assertEqual(_dbdstr.client, client)
            else:
                self.assertEqual(_dbdstr.client, "")

            #should be two revisions for our distributive
            self.assertEqual(1, DistributivesRevisions.objects(revision_of=_dbdstr).count())

    # Add distributive with parent list
    def test_add_with_parent(self):
        _first_distr = self._make_distr_json(1)
        _d_first_distr = self._add_verify_distr(_first_distr)
        _second_distr = self._make_distr_json(2)

        # by path
        _second_distr["parent"] = [{"path" : _first_distr.get("path")}]
        _d_second_distr = self._add_verify_distr(_second_distr)
        self.assertEqual(2, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(1, len(_d_second_distr.parent))
        self.assertIn(_first_distr.get("path"), _d_second_distr.parent[0].path)
        self.assertEqual(_d_second_distr.parent[0].citype, _first_distr.get("citype"))
        self.assertEqual(_d_second_distr.parent[0].version, _first_distr.get("version"))
        self.assertEqual(_d_second_distr.parent[0], _d_first_distr)

        # by checksum
        _third_distr = self._make_distr_json(3, client="TEST_CLIENT_1")
        _third_distr["parent"] = [{"checksum": _first_distr.get("checksum")}, {"path": _second_distr.get("path")}]
        _d_third_distr = self._add_verify_distr(_third_distr)
        self.assertEqual(3, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(2, len(_d_third_distr.parent))
        self.assertIn(_d_first_distr, _d_third_distr.parent)
        self.assertIn(_d_second_distr, _d_third_distr.parent)

        # by citype-version
        _fourth_distr = self._make_distr_json(4, client="TEST_CLIENT_1")
        _fourth_distr["parent"] = [
                {"citype": _first_distr.get("citype"), "version": _first_distr.get("version")},
                {"checksum": _second_distr.get("checksum")},
                {"path": _third_distr.get("path")}]
        _d_fourth_distr = self._add_verify_distr(_fourth_distr)
        self.assertEqual(4, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(3, len(_d_fourth_distr.parent))
        self.assertIn(_d_first_distr, _d_fourth_distr.parent)
        self.assertIn(_d_second_distr, _d_fourth_distr.parent)
        self.assertIn(_d_third_distr, _d_fourth_distr.parent)


        # some distr specified twice
        _fith_distr = self._make_distr_json(5, client="TEST_CLIENT_2")
        _fith_distr["parent"] = [
                {"checksum": _fourth_distr.get("checksum")},
                {"path": _fourth_distr.get("path")},
                {"citype": _fourth_distr.get("citype"),
                    "version": _fourth_distr.get("version"),
                    "client": _fourth_distr.get("client")}]
        _d_fith_distr = self._add_verify_distr(_fith_distr)
        self.assertEqual(5, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(1, len(_d_fith_distr.parent))
        self.assertIn(_d_fourth_distr, _d_fith_distr.parent)

        # non-existent parent
        _none_distr = self._make_distr_json("lazhaa")
        _sixth_distr = self._make_distr_json(6, client="TEST_CLIENT_2")
        _sixth_distr["parent"] = [
                {"checksum": _none_distr.get("checksum")},
                {"path": _none_distr.get("path")},
                {"citype": _none_distr.get("citype"), "version": _none_distr.get("version")}]
        _d_sixth_distr = self._add_verify_distr(_sixth_distr)
        self.assertEqual(6, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(0, len(_d_sixth_distr.parent))

        # wrong parent format: citype - only, without version and so on
        _seventh_distr = self._make_distr_json(7, client="TEST_CLIENT_3")
        _seventh_distr["parent"] = [
                {"citype": _sixth_distr.get("citype")},
                {"version": _fith_distr.get("version")},
                {"lazhaa": _none_distr.get("checksum")}]
        _d_seventh_distr = self._add_verify_distr(_seventh_distr)
        self.assertEqual(7, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(0, len(_d_seventh_distr.parent))

        _eith_distr = self._make_distr_json(8, client="TEST_CLIENT_3")
        _eith_distr["parent"] = [
                {"citype": _sixth_distr.get("citype"),
                    "version": _sixth_distr.get("version"),
                    "client": _sixth_distr.get("client") } ]
        _d_eith_distr = self._add_verify_distr(_eith_distr)
        self.assertEqual(8, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(1, len(_d_eith_distr.parent))
        self.assertIn(_d_sixth_distr, _d_eith_distr.parent)

    # add same distr with client and without it
    def test_add_with_and_without_client(self):
        self.assertEqual(0, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())

        client = f"TEST_CLIENT"
        _d = self._make_distr_json(1)
        _citype = _d.get("citype")
        _version = _d.get("version")
        _dbdstr = self._add_verify_distr(_d)
        self.assertEqual(1, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(1, _dbdstr.revision)
        self.assertEqual(1, len(_dbdstr.path))
        self.assertEqual(1, len(_dbdstr.checksum))
        self.assertEqual(0, len(_dbdstr.parent))

        _d = self._make_distr_json(2, client=client)
        _d["citype"] = _citype
        _d["version"] = _version
        _dbdstr = self._add_verify_distr(_d)
        self.assertEqual(2, Distributives.objects.count())
        self.assertEqual(0, DistributivesRevisions.objects.count())
        self.assertEqual(1, _dbdstr.revision)
        self.assertEqual(1, len(_dbdstr.path))
        self.assertEqual(1, len(_dbdstr.checksum))
        self.assertEqual(0, len(_dbdstr.parent))


    # Add distributive with existent path
    def test_add_existent_path(self):
        _orig_distr = self._make_distr_json(3, client="TEST_CLIENT")
        _d_orig = self._add_verify_distr(_orig_distr)
        _clone_distr = self._make_distr_json(4)
        _clone_distr["path"] = _orig_distr.get("path")
        _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=_clone_distr)
        self.assertEqual(_response.status_code, 409)
        self.assertEqual(1, Distributives.objects.count())

    # Add distributive with existent checksum
    def test_add_existent_checksum(self):
        _orig_distr = self._make_distr_json(0, client="TEST_CLIENT")
        _d_orig = self._add_verify_distr(_orig_distr)
        _clone_distr = self._make_distr_json(1)
        _clone_distr["checksum"] = _orig_distr.get("checksum")
        _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=_clone_distr)
        self.assertEqual(_response.status_code, 409)
        self.assertEqual(1, Distributives.objects.count())

    # Add distributive with incomplete data
    def test_add_incomplete_data(self):
        # citype absent
        # version absent
        # path absent
        # checksum absent
        for _fld in ["citype", "version", "path", "checksum"]:
            _distr = self._make_distr_json(len(_fld), client="TEST_CLIENT")
            del(_distr[_fld])
            _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=_distr)
            self.assertEqual(_response.status_code, 400)
            self.assertEqual(0, Distributives.objects.count())

    # add with something wrong in the request
    def test_add__parents_wrong_type(self):
        _first_distr = self._make_distr_json(1)
        _d_first_distr = self._add_verify_distr(_first_distr)
        _second_distr = self._make_distr_json(2)

        _second_distr["parent"] = True
        _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=_second_distr)
        self.assertEqual(_response.status_code, 400)

    # Update distributive - not exist
    def test_update_unexistent(self):
        _changes = {"path": "new.path:new.art:new.vers:new_pkg:new_clsf"}
        _nr_obj = Distributives.objects.count()
        _d = self._make_search_payload(self._make_distr_json(1))
        self.assertIn(_d.get("client"), [None, ""])
        self.assertEqual(0, len(Distributives.objects(
            citype=_d.get("citype"),
            version=_d.get("version"),
            client="")))

        _d["changes"] = _changes

        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_d)
        self.assertEqual(_response.status_code, 404)
        self.assertEqual(_nr_obj, Distributives.objects.count())

        _d["client"] = "TEST_CLIENT"
        self.assertEqual(0, len(Distributives.objects(
            citype=_d.get("citype"),
            version=_d.get("version"),
            client=_d.get("client"))))

        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_d)
        self.assertEqual(_response.status_code, 404)
        self.assertEqual(_nr_obj, Distributives.objects.count())

    # Update distributive - append path
    def test_update_append_path(self):
        _orig = self._make_distr_json(0)
        self._add_verify_distr(_orig)
        _fake = list(map(lambda x: self._make_distr_json(x, client=f"TEST_CLIENT_{x}"), [1, 2, 3]))

        # by ckecksum
        _rq = {"checksum": _orig.get("checksum"), "changes": {"path": _fake[0].get("path")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(201, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(2, len(_distr.path))
        self.assertIn(_fake[0].get("path"), _distr.path)
        self.assertEqual(_distr.revision, 1)
        _revisions = (DistributivesRevisions.objects(revision_of=_distr))
        self.assertEqual(_revisions.count(), 0)

        # by path
        _rq = {"path": _fake[0].get("path"), "changes": {"path": _fake[1].get("path")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(201, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(3, len(_distr.path))
        self.assertIn(_fake[1].get("path"), _distr.path)
        self.assertEqual(_distr.revision, 1)
        _revisions = (DistributivesRevisions.objects(revision_of=_distr))
        self.assertEqual(_revisions.count(), 0)

        # by type-version-client
        _rq = {"citype": _orig.get("citype"),
                "version": _orig.get("version"),
                "client": _orig.get("client"),
                "changes": {"path": _fake[2].get("path")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(201, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.path))
        self.assertIn(_fake[2].get("path"), _distr.path)
        self.assertEqual(_distr.revision, 1)
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        # by ckecksum
        # with existent path
        # should not be changed
        _rq = {"checksum": _orig.get("checksum"), "changes": {"path": _fake[0].get("path")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(200, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.path))
        self.assertEqual(_distr.revision, 1)
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        # by path
        # with existent path
        # should not be changed
        _rq = {"path": _fake[1].get("path"), "changes": {"path": _fake[2].get("path")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(200, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.path))
        self.assertEqual(_distr.revision, 1)
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        # by type-version-client
        # with existent path
        # should not be changed
        _rq = {"citype": _orig.get("citype"),
                "version": _orig.get("version"),
                "client": _orig.get("client"),
                "changes": {"path": _fake[0].get("path")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(200, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.path))
        self.assertEqual(_distr.revision, 1)
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        for _pth in list(map(lambda x: x.get("path"), _fake)):
            self.assertIn(_pth, _distr.path)

    # Update distributive - append checksum
    def test_update_append_checksum(self):
        _orig = self._make_distr_json(0)
        self._add_verify_distr(_orig)
        _fake = list(map(lambda x: self._make_distr_json(x, client=f"TEST_CLIENT_{x}"), [1, 2, 3]))

        # by ckecksum
        _rq = {"checksum": _orig.get("checksum"), "changes": {"checksum": _fake[0].get("checksum")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(201, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(2, len(_distr.checksum))
        self.assertIn(_fake[0].get("checksum"), _distr.checksum)

        _revisions = DistributivesRevisions.objects(revision_of=_distr)
        self.assertEqual(_revisions.count(), 0)

        # by path
        _rq = {"path": _orig.get("path"), "changes": {"checksum": _fake[1].get("checksum")}}

        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(201, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(3, len(_distr.checksum))
        self.assertIn(_fake[1].get("checksum"), _distr.checksum)
        _revisions = DistributivesRevisions.objects(revision_of=_distr)
        self.assertEqual(_revisions.count(), 0)

        # by type-version-client
        _rq = {"citype": _orig.get("citype"),
                "version": _orig.get("version"),
                "client": _orig.get("client"),
                "changes": {"checksum": _fake[2].get("checksum")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(201, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.checksum))
        self.assertIn(_fake[2].get("checksum"), _distr.checksum)
        _revisions = DistributivesRevisions.objects(revision_of=_distr)
        self.assertEqual(_revisions.count(), 0)

        # by ckecksum
        # with existent path
        # should not be changed
        _rq = {"checksum": _fake[1].get("checksum"), "changes": {"checksum": _fake[0].get("checksum")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(200, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.checksum))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        # by path
        # with existent checksum
        # should not be changed
        _rq = {"path": _orig.get("path"), "changes": {"checksum": _fake[1].get("checksum")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(200, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.checksum))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        # by type-version-client
        # with existent checksum
        # should not be changed
        _rq = {"citype": _orig.get("citype"),
                "version": _orig.get("version"),
                "client": _orig.get("client"),
                "changes": {"checksum": _fake[2].get("checksum")}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json = _rq)
        self.assertEqual(200, _response.status_code)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.checksum))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        for _checksum in list(map(lambda x: x.get("checksum"), _fake)):
            self.assertIn(_checksum, _distr.checksum)

    # Update distributive - replace parent
    def test_update_replace_parents(self):
        _fake_parent = self._make_distr_json("fake", client="TEST_CLIENT", citype="FAKEDSTRCLIENT")
        _real_standard_parents = list(map(lambda x: self._make_distr_json(x, citype="PRDDSTR"), [1, 2, 3]))
        _real_customer_parents = list(map(
            lambda x: self._make_distr_json(x, citype="PRDDSTRCLIENT", client="TEST_CLIENT"), [4, 5, 6]))

        _d_real_standard_parents = list(map(lambda x: self._add_verify_distr(x), _real_standard_parents))
        _d_real_customer_parents = list(map(lambda x: self._add_verify_distr(x), _real_customer_parents))

        _orig = self._make_distr_json("f1", client="SUPER_PUPER_TEST_CLIENT")
        _distr = self._add_verify_distr(_orig)
        self.assertEqual(0, len(_distr.parent))

        # by checksum
        _rq = {"checksum": _orig.get("checksum"), "changes":
                {"parent": [
                    {"path": _fake_parent.get("path")},
                    {"checksum": _real_standard_parents[0].get("checksum")},
                    {"citype": _real_standard_parents[1].get("citype"),
                        "version": _real_standard_parents[1].get("version")}
                    ]}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 201)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(2, len(_distr.parent))
        self.assertIn(_d_real_standard_parents[0], _distr.parent)
        self.assertIn(_d_real_standard_parents[1], _distr.parent)
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        # by path
        _rq = {"path": _orig.get("path"), "changes":
                {"parent": [
                    {"checksum": _fake_parent.get("checksum")},
                    {"path": _real_standard_parents[1].get("path")},
                    {"checksum": _real_standard_parents[2].get("checksum")},
                    {"citype": _real_customer_parents[0].get("citype"),
                        "version": _real_standard_parents[1].get("version")} # should not be seen - 'client' not given
                    ]}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 201)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(2, len(_distr.parent))
        self.assertIn(_d_real_standard_parents[1], _distr.parent)
        self.assertIn(_d_real_standard_parents[2], _distr.parent)
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

        # by citype-version-client
        _rq = {"citype": _orig.get("citype"),
                "version": _orig.get("version"),
                "client": _orig.get("client"),
                "changes":{
                    "parent": [
                        {"citype": _fake_parent.get("citype"),
                            "version": _fake_parent.get("version"),
                            "client": _fake_parent.get("client")},
                        {"citype": _real_standard_parents[0].get("citype"),
                            "version": _real_standard_parents[0].get("version")}, # shoud be seen
                        {"path": _real_customer_parents[0].get("path")},
                        {"checksum": _real_customer_parents[1].get("checksum")},
                        {"citype": _real_customer_parents[2].get("citype"),
                            "version": _real_customer_parents[2].get("version"),
                            "client": _real_customer_parents[2].get("client")}
                        ]}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 201)
        _distr = Distributives.objects.get(
                citype=_orig.get("citype"),
                version=_orig.get("version"),
                client=_orig.get("client", ""))
        self.assertEqual(4, len(_distr.parent))

        for _rcp in _d_real_customer_parents:
            self.assertIn(_rcp, _distr.parent)

        self.assertIn(_d_real_standard_parents[0], _distr.parent)
        self.assertEqual(DistributivesRevisions.objects(revision_of=_distr).count(), 0)

    # Update distributive - change 'artifact_deliverable'
    def test_update_artifact_deliverable(self):
        _distr = [self._make_distr_json(0)]

        for _i in range(1, 9):
            _distr.append(self._make_distr_json(_i, client=f"TEST_CLIENT_{_i}", citype=f"TEST{_i}DSTRCLIENT"))

        _is_dlv = True

        for _distr_c in _distr:
            _distr_c["artifact_deliverable"] = _is_dlv
            _d_distr_c = self._add_verify_distr(_distr_c)

            # by path
            _is_dlv = not _d_distr_c.artifact_deliverable
            _rq = {"path": _distr_c.get("path"), "changes":{
                "artifact_deliverable": _is_dlv}}

            # not allowed without a comment
            _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
            self.assertEqual(_response.status_code, 400)

            _rq = {"path": _distr_c.get("path"), "changes":{
                "artifact_deliverable": _is_dlv, "commentary": "First Change IsDlv to %s" % str(_is_dlv)}}
            _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
            self.assertEqual(_response.status_code, 201)
            _d_distr_c = Distributives.objects.get(
                    citype = _distr_c.get("citype"),
                    version = _distr_c.get("version"),
                    client = _distr_c.get("client", ""))
            self.assertEqual(_is_dlv, _d_distr_c.artifact_deliverable)
            self.assertEqual(1, DistributivesRevisions.objects(revision_of=_d_distr_c).count())

            # by checksum
            _is_dlv = not _d_distr_c.artifact_deliverable
            _rq = {"checksum": _distr_c.get("checksum"), "changes":{
                "artifact_deliverable": _is_dlv, "commentary": "Second Change IsDlv to %s" % str(_is_dlv)}}
            _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
            self.assertEqual(_response.status_code, 201)
            _d_distr_c = Distributives.objects.get(
                    citype = _distr_c.get("citype"),
                    version = _distr_c.get("version"),
                    client = _distr_c.get("client", ""))
            self.assertEqual(_is_dlv, _d_distr_c.artifact_deliverable)
            self.assertEqual(2, DistributivesRevisions.objects(revision_of=_d_distr_c).count())

            # by citype-version-client
            _is_dlv = not _d_distr_c.artifact_deliverable
            _rq = {"citype": _distr_c.get("citype"),
                    "version": _distr_c.get("version"),
                    "changes":{"artifact_deliverable": _is_dlv, "commentary": "Third Change IsDlv to %s" % str(_is_dlv)}}

            if _distr_c.get("client"):
                _rq["client"] = _distr_c.get("client")

            _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
            self.assertEqual(_response.status_code, 201)
            _d_distr_c = Distributives.objects.get(
                    citype = _distr_c.get("citype"),
                    version = _distr_c.get("version"),
                    client = _distr_c.get("client", ""))
            self.assertEqual(_is_dlv, _d_distr_c.artifact_deliverable)
            self.assertEqual(3, DistributivesRevisions.objects(revision_of=_d_distr_c).count())
            _is_dlv = not _d_distr_c.artifact_deliverable

    #Update distributive - change citype
    def test_update_citype(self):
        _source_citype = "TST1DSTR"
        _dest_citype = "TST2DSTR"

        _distr = self._make_distr_json(1, citype=_source_citype)
        _d_distr = self._add_verify_distr(_distr)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"citype": _dest_citype}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.citype, _source_citype)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"citype": _dest_citype}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.citype, _source_citype)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "changes": {"citype": _dest_citype}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.citype, _source_citype)

        # the same for customer-specific
        _source_citype = "TST1DSTRCLIENT"
        _dest_citype = "TST2DSTRCLIENT"

        _distr = self._make_distr_json(2, citype=_source_citype, client="TEST_CLIENT")
        _d_distr = self._add_verify_distr(_distr)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"citype": _dest_citype}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.citype, _source_citype)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"citype": _dest_citype}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.citype, _source_citype)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "client": _distr.get("client"),
                "changes": {"citype": _dest_citype}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.citype, _source_citype)

    # Update distributive - change version
    def test_update_change_version(self):
        _distr = self._make_distr_json(3)
        _source_version = _distr.get("version")
        _dest_version = '-'.join([_source_version, '%04d' % random.randint(0,9999)])
        _d_distr = self._add_verify_distr(_distr)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"version": _dest_version}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.version, _source_version)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"version": _dest_version}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.version, _source_version)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "changes": {"version": _dest_version}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.version, _source_version)

        # the same for customer-specific
        _distr = self._make_distr_json(4, client="TEST_CLIENT")
        _source_version = _distr.get("version")
        _dest_version = '-'.join([_source_version, '%04d' % random.randint(0,9999)])
        _d_distr = self._add_verify_distr(_distr)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"version": _dest_version}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.version, _source_version)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"version": _dest_version}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.version, _source_version)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "client": _distr.get("client"),
                "changes": {"version": _dest_version}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.version, _source_version)

    # Update distributive - change client
    def test_update_change_client(self):
        # assign client to standard distributive
        _source_client = ""
        _dest_client = "TEST_CLIENT_2"
        _distr = self._make_distr_json(5)
        _d_distr = self._add_verify_distr(_distr)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"client": _dest_client}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.client, _source_client)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"client": _dest_client}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.client, _source_client)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "changes": {"version": _dest_client}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.client, _source_client)

        # the same for customer-specific
        _source_client = "TEST_CLIENT_3"
        _dest_client = "TEST_CLIENT_4"
        _distr = self._make_distr_json(6, client=_source_client)
        _d_distr = self._add_verify_distr(_distr)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"client": _dest_client}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.client, _source_client)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"client": _dest_client}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.client, _source_client)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "client": _distr.get("client"),
                "changes": {"client": _dest_client}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertEqual(_d_distr_g.client, _source_client)

    # Update distributive - change actuality
    def test_update_change_actuality(self):
        # assign client to standard distributive
        _distr = self._make_distr_json(7)
        _d_distr = self._add_verify_distr(_distr)
        self.assertTrue(_d_distr.is_actual)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"is_actual": False}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"is_actual": False}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "changes": {"is_actual": False}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

        # the same for customer-specific
        _distr = self._make_distr_json(8, client="TEST_CLIENT_6")
        _d_distr = self._add_verify_distr(_distr)

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"is_actual": False}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"is_actual": False}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "client": _distr.get("client"),
                "changes": {"is_actual": False}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

        # the same vice-versa: from False to True
        # assign client to standard distributive
        _distr = self._make_distr_json(9)
        _d_distr = self._add_verify_distr(_distr)
        _d_distr.is_actual = False
        _d_distr.save()

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"is_actual": True}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 404)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"is_actual": True}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 404)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "changes": {"is_actual": True}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 404)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)

        # the same for customer-specific
        _distr = self._make_distr_json(10, client="TEST_CLIENT_6")
        _d_distr = self._add_verify_distr(_distr)
        _d_distr.is_actual = False
        _d_distr.save()

        # by path
        _rq = {"path": _distr.get("path"), "changes": {"is_actual": True}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 404)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)

        # by checksum
        _rq = {"checksum": _distr.get("checksum"), "changes": {"is_actual": True}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 404)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)

        # by citype-version-client
        _rq = {"citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "client": _distr.get("client"),
                "changes": {"is_actual": True}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 404)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
    
    #Update distributive - commentary only
    def test_update_change_commentary(self):
        # assign client to standard distributive
        _distr = self._make_distr_json(7)
        _d_distr = self._add_verify_distr(_distr)
        self.assertTrue(_d_distr.is_actual)

        _rq = {"path": _distr.get("path"), "changes": {"commentary": "New commentary (test user - 08.10.2021)"}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 201)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(_d_distr_g.commentary, "New commentary (test user - 08.10.2021)")

    #Delete distributive - by citype only
    def test_delete_by_citype(self):
        _citype = "TSTDSTR"
        _distr = self._make_distr_json(1, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"citype": _distr.get("citype")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

        # customer-specific
        _citype = "TSTDSTRCLIENT"
        _distr = self._make_distr_json(2, citype=_citype, client="TEST_CLIENT_1")
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"citype": _distr.get("citype")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)

    #Delete distributive - by checksum only
    def test_delete_checksum(self):
        _citype = "TSTDSTR"
        _distr = self._make_distr_json(1, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"checksum": _distr.get("checksum")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # customer-specific
        _citype = "TSTDSTRCLIENT"
        _distr = self._make_distr_json(2, citype=_citype, client="TEST_CLIENT_1")
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"checksum": _distr.get("checksum")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # the same for non-existent checksum
        _citype = "TSTDSTR"
        _distr = self._make_distr_json(3, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)
        _distr_x = self._make_distr_json(4, citype=_citype)

        _rq = {"checksum": _distr_x.get("checksum")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        self.assertEqual(0, Distributives.objects(
                    citype = _distr_x.get("citype"),
                    version = _distr_x.get("version"),
                    client = _distr_x.get("client", "")).count())
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # customer-specific
        _citype = "TSTDSTRCLIENT"
        _distr = self._make_distr_json(5, citype=_citype, client="TEST_CLIENT_2")
        _d_distr = self._add_verify_distr(_distr)
        _distr_x = self._make_distr_json(6, citype=_citype, client="TEST_CLIENT_2")

        _rq = {"checksum": _distr_x.get("checksum")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        self.assertEqual(0, Distributives.objects(
                    citype = _distr_x.get("citype"),
                    version = _distr_x.get("version"),
                    client = _distr_x.get("client", "")).count())
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

    # Delete distributive - by citype and version
    def test_delete_citype_version(self):
        _citype = "TSTDSTR"
        _distr = self._make_distr_json(1, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"citype": _distr.get("citype"), "version": _distr.get("version")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 0)

        # customer-specific
        _citype = "TSTDSTRCLIENT"
        _distr = self._make_distr_json(2, citype=_citype, client="TEST_CLIENT_1")
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"citype": _distr.get("citype"), "version": _distr.get("version")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # the same for non-existent pair
        _citype = "TSTDSTR"
        _distr = self._make_distr_json(3, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)
        _distr_x = self._make_distr_json(4, citype="TST6DSTR")

        _rq = {"citype": _distr_x.get("citype"), "version": _distr_x.get("version")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        self.assertEqual(0, Distributives.objects(
                    citype = _distr_x.get("citype"),
                    version = _distr_x.get("version"),
                    client = _distr_x.get("client", "")).count())
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # customer-specific
        _citype = "TSTDSTRCLIENT"
        _distr = self._make_distr_json(5, citype=_citype, client="TEST_CLIENT_2")
        _d_distr = self._add_verify_distr(_distr)
        _distr_x = self._make_distr_json(6, citype=_citype, client="TEST_CLIENT_2")

        _rq = {"citype": _distr_x.get("citype"), "version": _distr_x.get("version")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        self.assertEqual(0, Distributives.objects(
                    citype = _distr_x.get("citype"),
                    version = _distr_x.get("version"),
                    client = _distr_x.get("client", "")).count())
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

    #Delete distributive - by citype and version and client
    def test_delete_citype_version_client(self):
        # standard distributive but with client specified
        _citype = "TST1DSTR"
        _client = "TEST_CLIENT_1"
        _distr = self._make_distr_json(1, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"citype": _distr.get("citype"), "version": _distr.get("version"), "client": _client}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        self.assertEqual(0, Distributives.objects(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _client).count())
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # client-specific distributive
        _citype = "TST2DSTR"
        _client = "TEST_CLIENT_2"
        _distr = self._make_distr_json(2, citype=_citype, client=_client)
        _d_distr = self._add_verify_distr(_distr)

        _rq = {"citype": _distr.get("citype"), "version": _distr.get("version"), "client":_distr.get("client")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client"))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 0)

        # client-specific but wrong citype-version-client
        _citype = "TST3DSTR"
        _client = "TEST_CLIENT_3"
        _distr = self._make_distr_json(3, citype=_citype, client=_client)
        _d_distr = self._add_verify_distr(_distr)
        _distr_x = self._make_distr_json(4, citype="TST4DSTR", client="TEST_CLIENT_4")

        _rq = {"citype": _distr_x.get("citype"), "version": _distr_x.get("version"), "client":_distr_x.get("client")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        self.assertEqual(0, Distributives.objects(
                    citype = _distr_x.get("citype"),
                    version = _distr_x.get("version"),
                    client = _distr_x.get("client")).count())
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client"))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

    #Delete distributive - by path (last)
    def test_delete_by_path__last(self):
        # standard distribution
        # path exists
        _citype = "TST11DSTR"
        _distr = self._make_distr_json(11, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)
        self.assertEqual(len(_d_distr.path), 1)

        _rq = {"path": _distr.get("path")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 0)

        # path not exists
        _citype = "TST12DSTR"
        _distr = self._make_distr_json(12, citype=_citype)
        _d_distr = self._add_verify_distr(_distr)
        self.assertEqual(len(_d_distr.path), 1)

        _rq = {"path": _distr.get("path")+":nonexistant"}
        self.assertEqual(0, Distributives.objects(path=_rq.get("path")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)
        self.assertIn(_distr.get("path"), _d_distr_g.path)

        # customer-specific distribution
        # path exists
        _citype = "TST13DSTRCLIENT"
        _client = "TEST_CLIENT_13"
        _distr = self._make_distr_json(13, citype=_citype, client=_client)
        _d_distr = self._add_verify_distr(_distr)
        self.assertEqual(len(_d_distr.path), 1)

        _rq = {"path": _distr.get("path")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 0)

        # path not exists
        _citype = "TST14DSTRCLIENT"
        _client = "TEST_CLIENT_14"
        _distr = self._make_distr_json(14, citype=_citype, client=_client)
        _d_distr = self._add_verify_distr(_distr)
        self.assertEqual(len(_d_distr.path), 1)

        _rq = {"path": _distr.get("path")+":nonexistant"}
        self.assertEqual(0, Distributives.objects(path=_rq.get("path")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)
        self.assertIn(_distr.get("path"), _d_distr_g.path)

    #Delete distributive - by path (not last)
    def test_delete_by_path__notlast(self):
        # standard distribution
        # path exists
        _citype = "TST15DSTR"
        _distr = self._make_distr_json(15, citype=_citype)
        _alt_path = ":".join([_distr.get("path"), "alternative"])
        _d_distr = self._add_verify_distr(_distr)
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json={
            "path": _distr.get("path"),
            "changes": {"path": _alt_path}})
        self.assertEqual(201, _response.status_code)
        _d_distr = Distributives.objects.get(
                citype=_distr.get("citype"),
                version=_distr.get("version"),
                client=_distr.get("client", ""))
        self.assertEqual(len(_d_distr.path), 2)

        _rq = {"path": _distr.get("path")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)
        self.assertIn(_alt_path, _d_distr_g.path)

        # path not exists
        _citype = "TST16DSTR"
        _distr = self._make_distr_json(16, citype=_citype)
        _alt_path = ":".join([_distr.get("path"), "alternative"])
        _absent_path = ":".join([_distr.get("path"), "nonexistant"])
        _d_distr = self._add_verify_distr(_distr)
        self.assertEqual(len(_d_distr.path), 1)
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json={
            "path": _distr.get("path"),
            "changes": {"path": _alt_path}})
        self.assertEqual(201, _response.status_code)
        _d_distr = Distributives.objects.get(
                citype=_distr.get("citype"),
                version=_distr.get("version"),
                client=_distr.get("client", ""))
        self.assertEqual(len(_d_distr.path), 2)
        self.assertNotIn(_absent_path, _d_distr.path)

        _rq = {"path": _absent_path}
        self.assertEqual(0, Distributives.objects(path=_rq.get("path")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 2)
        self.assertIn(_distr.get("path"), _d_distr_g.path)
        self.assertIn(_alt_path, _d_distr_g.path)

        # customer-specific distribution
        # path exists
        _citype = "TST17DSTR"
        _client = "TEST_CLIENT_17"
        _distr = self._make_distr_json(17, citype=_citype, client=_client)
        _alt_path = ":".join([_distr.get("path"), "alternative"])
        _d_distr = self._add_verify_distr(_distr)
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json={
            "path": _distr.get("path"),
            "changes": {"path": _alt_path}})
        self.assertEqual(201, _response.status_code)
        _d_distr = Distributives.objects.get(
                citype=_distr.get("citype"),
                version=_distr.get("version"),
                client=_distr.get("client", ""))
        self.assertEqual(len(_d_distr.path), 2)

        _rq = {"path": _distr.get("path")}
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)
        self.assertIn(_alt_path, _d_distr_g.path)

        # path not exists
        _citype = "TST18DSTR"
        _client = "TEST_CLIENT_18"
        _distr = self._make_distr_json(18, citype=_citype, client=_client)
        _alt_path = ":".join([_distr.get("path"), "alternative"])
        _absent_path = ":".join([_distr.get("path"), "nonexistant"])
        _d_distr = self._add_verify_distr(_distr)
        self.assertEqual(len(_d_distr.path), 1)
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json={
            "path": _distr.get("path"),
            "changes": {"path": _alt_path}})
        self.assertEqual(201, _response.status_code)
        _d_distr = Distributives.objects.get(
                citype=_distr.get("citype"),
                version=_distr.get("version"),
                client=_distr.get("client", ""))
        self.assertEqual(len(_d_distr.path), 2)
        self.assertNotIn(_absent_path, _d_distr.path)

        _rq = {"path": _absent_path}
        self.assertEqual(0, Distributives.objects(path=_rq.get("path")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertTrue(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 2)
        self.assertIn(_distr.get("path"), _d_distr_g.path)
        self.assertIn(_alt_path, _d_distr_g.path)

    # Delete distributive - deleted already
    def test_delete_deleted(self):
        ## STANDARD
        _distr = self._make_distr_json(20)
        _d_distr = self._add_verify_distr(_distr)
        _d_distr.is_actual = False
        _d_distr.save()

        # by path
        _rq = {"path": _distr.get("path")}
        self.assertEqual(1, Distributives.objects(path=_rq.get("path")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # by checksum - must fail
        _rq = {"checksum": _distr.get("checksum")}
        self.assertEqual(1, Distributives.objects(checksum=_rq.get("checksum")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # by citype-version
        _rq = {"citype": _distr.get("citype"), "version": _distr.get("version")}
        self.assertEqual(1, Distributives.objects(citype=_rq.get("citype"),
            version=_rq.get("version"), client="").count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        ## CUSTOMER-SPECIFIC
        _distr = self._make_distr_json(21, client="TEST_CLIENT_21")
        _d_distr = self._add_verify_distr(_distr)
        _d_distr.is_actual = False
        _d_distr.save()

        # by path
        _rq = {"path": _distr.get("path")}
        self.assertEqual(1, Distributives.objects(path=_rq.get("path")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # by checksum - must fail
        _rq = {"checksum": _distr.get("checksum")}
        self.assertEqual(1, Distributives.objects(checksum=_rq.get("checksum")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 400)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

        # by citype-version
        _rq = {"citype": _distr.get("citype"), "version": _distr.get("version"), "client": _distr.get("client")}
        self.assertEqual(1, Distributives.objects(citype=_rq.get("citype"),
            version=_rq.get("version"), client=_rq.get("client")).count())
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=_rq)
        self.assertEqual(_response.status_code, 200)
        _d_distr_g = Distributives.objects.get(
                    citype = _distr.get("citype"),
                    version = _distr.get("version"),
                    client = _distr.get("client", ""))
        self.assertEqual(DistributivesRevisions.objects(revision_of=_d_distr_g).count(), 0)
        self.assertFalse(_d_distr_g.is_actual)
        self.assertEqual(len(_d_distr_g.path), 1)

    def _make_distr_jsons_for_get_tests(self):
        _num_distrs = random.randint(15, 23)

        _citype_template = "TEST%02dDSTR%s"
        _client_template = "TEST_CLIENT_%02d"
        _result = list()

        for _i in range(0, _num_distrs):
            _client = _client_template % (_i%3) if _i%3 else None
            _citype = _citype_template % (_i%3, "CLIENT" if _client else "")
            _result.append(self._make_distr_json(_i, client=_client, citype=_citype))

        return _result

    # Get distributives - all
    def test_get_distributives__all(self):
        # empty database
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"))
        self.assertEqual(_response.status_code, 200)
        self.assertEqual(0, len(_response.json))

        # add some distributives
        _all_distrs = self._make_distr_jsons_for_get_tests()

        for _distr in _all_distrs:
            self._add_verify_distr(_distr)

        # as_is
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"))
        self.assertEqual(_response.status_code, 200)
        _distrs = _response.json
        self.assertEqual(len(_distrs), len(_all_distrs))

        for _distr in _all_distrs:
            _single_distr = list(filter(lambda x: all([
                x.get("citype") == _distr.get("citype"),
                x.get("version") == _distr.get("version"),
                x.get("client","") == _distr.get("client", "")]), _distrs))

            self.assertEqual(1, len(_single_distr))
            _single_distr = _single_distr.pop()
            self.assertEqual(1, len(_single_distr.get("path")))
            self.assertIn(_distr.get("path"), _single_distr.get("path"))
            self.assertEqual(1, len(_single_distr.get("checksum")))
            self.assertIn(_distr.get("checksum"), _single_distr.get("checksum"))

        ### pop a half and delete it, then verify again
        for _t in range(0, int(len(_all_distrs)/2)):
            _distr = _all_distrs.pop()
            _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json={
                "citype": _distr.get("citype"),
                "version": _distr.get("version"),
                "client": _distr.get("client")})
            self.assertEqual(_response.status_code, 200)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"))
        self.assertEqual(_response.status_code, 200)
        _distrs = _response.json
        self.assertEqual(len(_distrs), len(_all_distrs))

        for _distr in _all_distrs:
            _single_distr = list(filter(lambda x: all([
                x.get("citype") == _distr.get("citype"),
                x.get("version") == _distr.get("version"),
                x.get("client", "") == _distr.get("client", "")]), _distrs))

            self.assertEqual(1, len(_single_distr))
            _single_distr = _single_distr.pop()
            self.assertEqual(1, len(_single_distr.get("path")))
            self.assertIn(_distr.get("path"), _single_distr.get("path"))
            self.assertEqual(1, len(_single_distr.get("checksum")))
            self.assertIn(_distr.get("checksum"), _single_distr.get("checksum"))

    # Get distributives - by type
    def test_get_distributives__type(self):
        _all_distrs = self._make_distr_jsons_for_get_tests()

        for _distr in _all_distrs:
            self._add_verify_distr(_distr)

        _citypes = list(set(map(lambda x: x.get("citype"), _all_distrs)))

        for _citype in _citypes:
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"citype": _citype})
            self.assertEqual(_response.status_code, 200)
            _distrs = _response.json

            for _distr in list(filter(lambda x: x.get("citype") == _citype, _all_distrs)):
                _single_distr = list(filter(lambda x: all([
                    x.get("citype") == _distr.get("citype"),
                    x.get("version") == _distr.get("version"),
                    x.get("client", "") == _distr.get("client", "")]), _distrs))

                self.assertEqual(1, len(_single_distr))
                _single_distr = _single_distr.pop()
                self.assertEqual(1, len(_single_distr.get("path")))
                self.assertIn(_distr.get("path"), _single_distr.get("path"))
                self.assertEqual(1, len(_single_distr.get("checksum")))
                self.assertIn(_distr.get("checksum"), _single_distr.get("checksum"))

                # now delete it
                _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"),
                        json=dict((_key,_distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr))
                self.assertEqual(200, _response.status_code)

            # verify list is empty now
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"citype": _citype})
            self.assertEqual(_response.status_code, 200)
            self.assertEqual(len(_response.json), 0)

    # Get distributives - by version
    def test_get_distributives__version(self):
        _all_distrs = self._make_distr_jsons_for_get_tests()

        for _i in range(len(_all_distrs), len(_all_distrs)*2):
            _distr = self._make_distr_json(_i, citype="TEST%02dDSTR" % _i)
            _distr["version"] = _all_distrs[int(_i/2)].get("version")
            _all_distrs.append(_distr)

        for _distr in _all_distrs:
            self._add_verify_distr(_distr)

        _versions = list(set(map(lambda x: x.get("version"), _all_distrs)))

        for _version in _versions:
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"version": _version})
            self.assertEqual(_response.status_code, 200)
            _distrs = _response.json

            for _distr in list(filter(lambda x: x.get("version") == _version, _all_distrs)):
                _single_distr = list(filter(lambda x: all([
                    x.get("citype") == _distr.get("citype"),
                    x.get("version") == _distr.get("version"),
                    x.get("client", "") == _distr.get("client", "")]), _distrs))

                self.assertEqual(1, len(_single_distr))
                _single_distr = _single_distr.pop()
                self.assertEqual(1, len(_single_distr.get("path")))
                self.assertIn(_distr.get("path"), _single_distr.get("path"))
                self.assertEqual(1, len(_single_distr.get("checksum")))
                self.assertIn(_distr.get("checksum"), _single_distr.get("checksum"))

                # now delete it
                _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"),
                        json=dict((_key,_distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr))
                self.assertEqual(200, _response.status_code)

            # verify list is empty now
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"version": _version})
            self.assertEqual(_response.status_code, 200)
            self.assertEqual(len(_response.json), 0)

    # Get distributives - by path
    def test_get_distributive__path(self):
        _all_distrs = self._make_distr_jsons_for_get_tests()

        for _distr in _all_distrs:
            _b_distr = self._add_verify_distr(_distr)
            _b_distr.path.append(':'.join([_distr.get("path"), "alternative"]))
            _b_distr.save()

        _paths = list(set(map(lambda x: x.get("path"), _all_distrs)))

        for _path in _paths:
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"path": _path})
            self.assertEqual(_response.status_code, 200)
            _distrs = _response.json

            for _distr in list(filter(lambda x: x.get("path") == _path, _all_distrs)):
                _single_distr = list(filter(lambda x: all([
                    x.get("citype") == _distr.get("citype"),
                    x.get("version") == _distr.get("version"),
                    x.get("client", "") == _distr.get("client", "")]), _distrs))

                self.assertEqual(1, len(_single_distr))
                _single_distr = _single_distr.pop()
                self.assertEqual(2, len(_single_distr.get("path")))
                self.assertIn(_distr.get("path"), _single_distr.get("path"))
                self.assertEqual(1, len(_single_distr.get("checksum")))
                self.assertIn(_distr.get("checksum"), _single_distr.get("checksum"))

                # now delete it
                _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"),
                        json={"path": _path})
                self.assertEqual(200, _response.status_code)

            # verify list is empty now
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"path": _path})
            self.assertEqual(_response.status_code, 200)
            self.assertEqual(len(_response.json), 0)

    # Get distributives - by checksum
    def test_get_distributive__checksum(self):
        _all_distrs = self._make_distr_jsons_for_get_tests()

        for _distr in _all_distrs:
            _b_distr = self._add_verify_distr(_distr)
            _b_distr.checksum.append(self._md5(':'.join([_distr.get("path"), "alternative"])))

            # try to save - and skip if checksum is not unique
            try:
                _b_distr.save()
            except:
                pass

        _checksums = list(set(map(lambda x: x.get("checksum"), _all_distrs)))

        for _checksum in _checksums:
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"checksum": _checksum})
            self.assertEqual(_response.status_code, 200)
            _distrs = _response.json

            for _distr in list(filter(lambda x: x.get("checksum") == _checksum, _all_distrs)):
                _single_distr = list(filter(lambda x: all([
                    x.get("citype") == _distr.get("citype"),
                    x.get("version") == _distr.get("version"),
                    x.get("client", "") == _distr.get("client", "")]), _distrs))

                self.assertEqual(1, len(_single_distr))
                _single_distr = _single_distr.pop()
                self.assertEqual(1, len(_single_distr.get("path")))
                self.assertIn(_distr.get("path"), _single_distr.get("path"))
                self.assertIn(len(_single_distr.get("checksum")), [1, 2])
                self.assertIn(_distr.get("checksum"), _single_distr.get("checksum"))

                # now delete it
                _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"),
                        json=dict((_key,_distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr))
                self.assertEqual(200, _response.status_code)

            # verify list is empty now
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"checksum": _checksum})
            self.assertEqual(_response.status_code, 200)
            self.assertEqual(len(_response.json), 0)


    # Get distributives - deliverable, non-deliverable
    def test_get_distributives__deliverable(self):
        _all_distrs = self._make_distr_jsons_for_get_tests()

        _artifact_deliverable = True
        for _distr in _all_distrs:
            _distr["artifact_deliverable"] = _artifact_deliverable
            _b_distr = self._add_verify_distr(_distr)
            _artifact_deliverable = not _artifact_deliverable

        for _artifact_deliverable in [True, False]:
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"artifact_deliverable": _artifact_deliverable})
            self.assertEqual(_response.status_code, 200)
            _distrs = _response.json

            for _distr in list(filter(lambda x: x.get("artifact_deliverable") == _artifact_deliverable, _all_distrs)):
                _single_distr = list(filter(lambda x: all([
                    x.get("citype") == _distr.get("citype"),
                    x.get("version") == _distr.get("version"),
                    x.get("client", "") == _distr.get("client", "")]), _distrs))

                self.assertEqual(1, len(_single_distr))
                _single_distr = _single_distr.pop()
                self.assertEqual(1, len(_single_distr.get("path")))
                self.assertIn(_distr.get("path"), _single_distr.get("path"))
                self.assertEqual(1, len(_single_distr.get("checksum")))
                self.assertIn(_distr.get("checksum"), _single_distr.get("checksum"))

                # now delete it
                _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"),
                        json=dict((_key,_distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr))
                self.assertEqual(200, _response.status_code)

            # verify list is empty now
            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"), json={"artifact_deliverable": _artifact_deliverable})
            self.assertEqual(_response.status_code, 200)
            self.assertEqual(len(_response.json), 0)

    # Get distributives - check parents
    def test_get_distributive__parents(self):
        _parent_one = self._make_distr_json(1, citype="TEST01DSTR")
        _parent_two = self._make_distr_json(2, citype="TEST02DSTR")
        _child = self._make_distr_json(3, citype="TEST03DSTRCLIENT", client="TEST_CLIENT_03")

        _b_parent_one = self._add_verify_distr(_parent_one)
        _b_parent_two = self._add_verify_distr(_parent_two)
        _child["parent"] = list(map(lambda x:
                dict((_key, x.get(_key)) for _key in ["citype", "version", "client"] if _key in x),
                [_parent_one, _parent_two]))
        _b_child = self._add_verify_distr(_child)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"))
        self.assertEqual(_response.status_code, 200)
        _all_distrs = _response.json
        self.assertEqual(len(_all_distrs), 3)

        _response_for_child = list(filter(lambda x: all([
            x.get("citype") == _child.get("citype"),
            x.get("version") == _child.get("version"),
            x.get("client") == _child.get("client")]), _all_distrs))
        self.assertEqual(len(_response_for_child), 1)
        _response_for_child = _response_for_child.pop()
        self.assertEqual(len(_response_for_child.get("parent")), 2)

        for _parent in [_parent_one, _parent_two]:
            self.assertEqual(len(list(filter(lambda x: all([
                x.get("citype") == _parent.get("citype"),
                x.get("version") == _parent.get("version"),
                x.get("client", "") == _parent.get("client", "")]), _response_for_child.get("parent")))), 1)

        # now delete "parent_one" and make all the same
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=
                dict((_key, _parent_one.get(_key)) for _key in ["citype", "version", "client"] if _key in _parent_one))
        self.assertEqual(_response.status_code, 200)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributives"))
        self.assertEqual(_response.status_code, 200)
        _all_distrs = _response.json
        self.assertEqual(len(_all_distrs), 2)

        _response_for_child = list(filter(lambda x: all([
            x.get("citype") == _child.get("citype"),
            x.get("version") == _child.get("version"),
            x.get("client") == _child.get("client")]), _all_distrs))
        self.assertEqual(len(_response_for_child), 1)
        _response_for_child = _response_for_child.pop()
        self.assertEqual(len(_response_for_child.get("parent")), 2)

        for _parent in [_parent_one, _parent_two]:
            self.assertEqual(len(list(filter(lambda x: all([
                x.get("citype") == _parent.get("citype"),
                x.get("version") == _parent.get("version"),
                x.get("client", "") == _parent.get("client", "")]), _response_for_child.get("parent")))), 1)

    # Get distributive revisions - not found
    def test_distributive_revisions__not_found(self):
        _distr = self._make_distr_json(1)
        _notfound = self._make_distr_json(2)

        # empty db:
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"))
        self.assertEqual(_response.status_code, 400)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=
            dict((_key, _notfound.get(_key)) for _key in ["citype", "version", "client"] if _key in _notfound))
        self.assertEqual(_response.status_code, 404)
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=
            dict((_key, _distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr))
        self.assertEqual(_response.status_code, 404)

        # save our distr but ask for another one
        _b_distr = self._add_verify_distr(_distr)
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=
            dict((_key, _notfound.get(_key)) for _key in ["citype", "version", "client"] if _key in _notfound))
        self.assertEqual(_response.status_code, 404)

        # delete our distr and ask for another
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=
            dict((_key, _distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr))
        self.assertEqual(200, _response.status_code)
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=
            dict((_key, _notfound.get(_key)) for _key in ["citype", "version", "client"] if _key in _notfound))
        self.assertEqual(_response.status_code, 404)

        # ask for our deleted distr
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=
            dict((_key, _distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr))
        self.assertEqual(_response.status_code, 404)

    # Get distributive revisions - incomplete parameters (many found)
    def test_distributive_revisions__incomplete_parameter(self):
        # standard
        _citype = "TESTDSTR"
        _distrs = [
                self._make_distr_json(1, citype=_citype), 
                self._make_distr_json(2, citype=_citype)]

        for _distr in _distrs:
            self._add_verify_distr(_distr)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=
                {"citype": _citype})
        self.assertEqual(_response.status_code, 400)

        # customer-specific
        _citype = "TESTDSTRCLIENT"
        _client = "TEST_CLIENT"
        _distrs = [
                self._make_distr_json(3, citype=_citype, client=_client), 
                self._make_distr_json(4, citype=_citype, client=_client)]

        for _distr in _distrs:
            self._add_verify_distr(_distr)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=
                {"citype": _citype, "client": _client})
        self.assertEqual(_response.status_code, 400)

    # Get distributive revisions - by type - version - client
    def test_distributive_revisions__by_type_version_client(self):
        # standard, customer-specific
        _distr_list = [self._make_distr_json(1), self._make_distr_json(2, client="TEST_CLIENT")]

        for _distr in _distr_list:
            _b_dstr = self._add_verify_distr(_distr)
            self.assertEqual(DistributivesRevisions.objects(revision_of=_b_dstr).count(), 0)

        for _distr in _distr_list:
            _search_param = dict((_key, _distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _distr)

            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=_search_param)
            self.assertEqual(200, _response.status_code)
            _response_list = _response.json
            self.assertEqual(1, len(_response_list))
            _response_distr = _response_list.pop()
            self.assertTrue(_response_distr.get("artifact_deliverable"))
            self.assertTrue(_response_distr.get("commentary").startswith("Initial addition"))

            _change = _search_param.copy()
            _change["changes"] = {"path": ':'.join([_distr.get("path"), "alternative"]),
                    "commentary": "-".join([_response_distr.get("commentary", "No comments..."), "updated"])}
            _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_change)
            self.assertEqual(_response.status_code, 201)

            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=_search_param)
            _response_list = _response.json
            self.assertEqual(2, len(_response_list))
            _response_distr = _response_list.pop(0)
            self.assertEqual(2, _response_distr.get("revision"))
            self.assertEqual(_change.get("changes").get("commentary"), _response_distr.get("commentary"))
            _response_distr = _response_list.pop(0)
            self.assertEqual(1, _response_distr.get("revision"))
            self.assertNotEqual(_change.get("changes").get("commentary"), _response_distr.get("commentary"))

    # Get distributive revisions - by path
    def test_distributive_revisions__by_path(self):
        # standard, customer-specific
        _distr_list = [self._make_distr_json(1), self._make_distr_json(2, client="TEST_CLIENT")]

        for _distr in _distr_list:
            _b_dstr = self._add_verify_distr(_distr)
            self.assertEqual(DistributivesRevisions.objects(revision_of=_b_dstr).count(), 0)

        for _distr in _distr_list:
            _search_param = {"path": _distr.get("path")}

            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=_search_param)
            self.assertEqual(200, _response.status_code)
            _response_list = _response.json
            self.assertEqual(1, len(_response_list))
            _response_distr = _response_list.pop()
            self.assertTrue(_response_distr.get("artifact_deliverable"))
            self.assertTrue(_response_distr.get("commentary").startswith("Initial addition"))

            _change = _search_param.copy()
            _change["changes"] = {"path": ':'.join([_distr.get("path"), "alternative"]),
                    "commentary": "-".join([_response_distr.get("commentary", "No comments..."), "updated"])}
            _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_change)
            self.assertEqual(_response.status_code, 201)

            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=_search_param)
            _response_list = _response.json
            self.assertEqual(2, len(_response_list))
            _response_distr = _response_list.pop(0)
            self.assertEqual(_change.get("changes").get("commentary"), _response_distr.get("commentary"))
            self.assertEqual(2, _response_distr.get("revision"))
            _response_distr = _response_list.pop(0)
            self.assertEqual(1, _response_distr.get("revision"))
            self.assertNotEqual(_change.get("changes").get("commentary"), _response_distr.get("commentary"))

    # Get distributive revisions - by checksum
    def test_distributive_revisions__by_checksum(self):
        # standard, customer-specific
        _distr_list = [self._make_distr_json(1), self._make_distr_json(2, client="TEST_CLIENT")]

        for _distr in _distr_list:
            _b_dstr = self._add_verify_distr(_distr)
            self.assertEqual(DistributivesRevisions.objects(revision_of=_b_dstr).count(), 0)

        for _distr in _distr_list:
            _search_param = {"checksum": _distr.get("checksum")}

            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=_search_param)
            self.assertEqual(200, _response.status_code)
            _response_list = _response.json
            self.assertEqual(1, len(_response_list))
            _response_distr = _response_list.pop()
            self.assertTrue(_response_distr.get("artifact_deliverable"))
            self.assertTrue(_response_distr.get("commentary").startswith("Initial addition"))

            _change = _search_param.copy()
            _change["changes"] = {"path": ':'.join([_distr.get("path"), "alternative"]),
                    "commentary": '-'.join([_response_distr.get("commentary", "No Comments..."), "new"])}
            _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_change)
            self.assertEqual(_response.status_code, 201)

            _response = self.test_client.get(posixpath.join(posixpath.sep, "get_distributive_revisions"), json=_search_param)
            _response_list = _response.json
            self.assertEqual(2, len(_response_list))
            _response_distr = _response_list.pop(0)
            self.assertEqual(_change.get("changes").get("commentary"), _response_distr.get("commentary"))
            self.assertEqual(2, _response_distr.get("revision"))
            _response_distr = _response_list.pop(0)
            self.assertEqual(1, _response_distr.get("revision"))
            self.assertTrue(_response_distr.get("commentary").startswith("Initial addition"))

    # Get versions by type - empty
    def test_get_versions_by_citype__empty(self):
        _citype_ask = "TESTNONEXISTANTDSTR"

        _all_distrs = self._make_distr_jsons_for_get_tests()
        self.assertNotIn(_citype_ask, list(set(map(lambda x: x.get("citype"), _all_distrs))))

        for _distr in _all_distrs:
            self._add_verify_distr(_distr)

        # no search params
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"))
        self.assertEqual(400, _response.status_code)

        # wrong type
        _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"), json={"citype": _citype_ask})
        self.assertEqual(200, _response.status_code)
        self.assertEqual(len(_response.json), 0)

    # Get versions by type
    def test_get_versons_by_citype__ok(self):
        _all_distrs = self._make_distr_jsons_for_get_tests()
        _all_citypes = list(set(map(lambda x: x.get("citype"), _all_distrs)))
        _artifact_deliverable = True

        for _distr in _all_distrs:
            _distr["artifact_deliverable"] = _artifact_deliverable
            _b_dstr = self._add_verify_distr(_distr)
            _artifact_deliverable = not _artifact_deliverable


        for _i in range(1,3):
            # all
            # deliverable
            # not deliverable
            for _citype in _all_citypes:
                _all_type_distrs = list(filter(lambda x: x.get("citype") == _citype, _all_distrs))
                _all_type_versions = list(set(map(lambda x: x.get("version"), _all_type_distrs)))
                _deliverable_type_distrs = list(filter(lambda x: x.get("artifact_deliverable"), _all_type_distrs))
                _deliverable_type_versions = list(set(map(lambda x: x.get("version"), _deliverable_type_distrs)))
                _nondeliverable_type_distrs = list(filter(lambda x: not x.get("artifact_deliverable"), _all_type_distrs))
                _nondeliverable_type_versions = list(set(map(lambda x: x.get("version"), _nondeliverable_type_distrs)))

                _all_type_versions.sort()
                _deliverable_type_versions.sort()
                _nondeliverable_type_versions.sort()

                if not _citype.endswith("CLIENT"):
                    _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"), json={"citype": _citype})
                    self.assertEqual(_response.status_code, 200)
                    _response_list = _response.json
                    _response_list.sort()
                    self.assertEqual(_response_list, _all_type_versions)

                    _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"), 
                            json={"citype": _citype, "artifact_deliverable": True})
                    self.assertEqual(_response.status_code, 200)
                    _response_list = _response.json
                    _response_list.sort()
                    self.assertEqual(_response_list, _deliverable_type_versions)

                    _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"), 
                            json={"citype": _citype, "artifact_deliverable": False})
                    self.assertEqual(_response.status_code, 200)
                    _response_list = _response.json
                    _response_list.sort()
                    self.assertEqual(_response_list, _nondeliverable_type_versions)

                    continue

                _clients = list(set(map(lambda x: x.get("client"), _all_type_distrs)))

                for _client in _clients:
                    _all_client_distrs = list(filter(lambda x: x.get("client") == _client, _all_type_distrs))
                    _all_client_versions = list(set(map(lambda x: x.get("version"), _all_client_distrs)))
                    _deliverable_client_distrs = list(filter(lambda x: x.get("client") == _client,
                        _deliverable_type_distrs))
                    _deliverable_client_versions = list(set(map(lambda x: x.get("version"),
                        _deliverable_client_distrs)))
                    _nondeliverable_client_distrs = list(filter(lambda x: x.get("client") == _client, 
                        _nondeliverable_type_distrs))
                    _nondeliverable_client_versions = list(set(map(lambda x: x.get("version"), 
                        _nondeliverable_client_distrs)))

                    _all_client_versions.sort()
                    _deliverable_client_versions.sort()
                    _nondeliverable_client_versions.sort()

                    _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"), 
                            json={"citype": _citype, "client": _client})
                    self.assertEqual(_response.status_code, 200)
                    _response_list = _response.json
                    _response_list.sort()
                    self.assertEqual(_response_list, _all_client_versions)

                    _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"), 
                            json={"citype": _citype, "client": _client, "artifact_deliverable": True})
                    self.assertEqual(_response.status_code, 200)
                    _response_list = _response.json
                    _response_list.sort()
                    self.assertEqual(_response_list, _deliverable_client_versions)

                    _response = self.test_client.get(posixpath.join(posixpath.sep, "get_versions_by_citype"), 
                            json={"citype": _citype, "client": _client, "artifact_deliverable": False})
                    self.assertEqual(_response.status_code, 200)
                    _response_list = _response.json
                    _response_list.sort()
                    self.assertEqual(_response_list, _nondeliverable_client_versions)

            # delete a half of distrs and repeat verification
            for _x in range(0, int(len(_all_distrs)/2)):
                _dstr = _all_distrs[_x]
                self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), 
                        json=dict((_key, _dstr.get(_key)) for _key in ["citype", "version", "client"] if _key in _dstr))
                self.assertEqual(200, _response.status_code)

    def _check_new_ci_type_api(self, url, params, expected_results=0):
        _response = self.test_client.get(url, query_string=params)
        self.assertEqual(200, _response.status_code)
        _response_list = _response.json.get('values')
        self.assertEqual(expected_results, len(_response_list))
        self.assertEqual("100.00.101", _response_list[0].get('version'))
        _first_path = _response_list[0].get('paths')
        _first_checksums = _response_list[0].get('checksums')
        _response_new = self.test_client.get(url, query_string=params)
        _response_list_new = _response_new.json.get('values')
        self.assertEqual(_first_path, _response_list_new[0].get('paths'))
        self.assertEqual(_first_checksums, _response_list_new[0].get('checksums'))

    def test_get_versons_by_citype__new(self):
        _num_distrs = random.randint(15, 23)

        _citype_template = "TEST%02dDSTR%s"
        _client_template = "TEST_CLIENT_%02d"
        _all_distrs = list()

        for _i in range(0, _num_distrs):
            _client = _client_template % (_i%3) if _i%3 else None
            _citype = _citype_template % (_i%5, "CLIENT" if _client else "")
            _all_distrs.append(self._make_distr_json(_i, client=_client, citype=_citype))

        _all_citypes = list(set(map(lambda x: x.get("citype"), _all_distrs)))
        _latest_version = '100.00.101'

        for _citype in _all_citypes:
            if _citype.endswith('CLIENT'):
                continue

            _path = f"{_citype}.last_path:latest-artifact-id:${_latest_version}:ppp"
            _last_version = {
                    'path': _path,
                    'citype': _citype,
                    'version': _latest_version,
                    'checksum':  self._md5('$'.join([ _path, _citype, _latest_version]))
            }
            _all_distrs.append(_last_version)

        for _distr in _all_distrs:
            _distr["artifact_deliverable"] = True
            _b_dstr = self._add_verify_distr(_distr)

        _num_paths = random.randint(2, 5)

        for _citype in _all_citypes:
            if _citype.endswith('CLIENT'):
                continue

            for _i in range(0, _num_paths):
                _local_path =  f"gg{_i}:aa{_i}:{random.randint(0,99)}:pp{_i}"
                _local_md5 = self._md5('$'.join([ _local_path, _citype, _latest_version]))
                _extend_distr = {
                        "changes": {
                            "path": _local_path,
                            "checksum": _local_md5
                        },
                        "citype": _citype,
                        "version": _latest_version
                }
                _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_extend_distr)
                self.assertEqual(201, _response.status_code)

        # check one ci_type
        # check two ci_types
        _ci_types_to_check = list(filter(lambda x: not x.endswith('CLIENT'), _all_citypes))[:2]
        _url = posixpath.join(posixpath.sep, "versions_by_citype", "latest")
        self._check_new_ci_type_api(url=_url,
                params={"ci_type": _ci_types_to_check[0]}, expected_results=1)
        self._check_new_ci_type_api(url=_url,
                params={"ci_type": _ci_types_to_check}, expected_results=2)
        self._check_new_ci_type_api(url=_url,
                params={"ci_type": [_ci_types_to_check[0], "NONEXISTENT"]}, expected_results=1)
        _response = self.test_client.get(_url, 
                query_string={"ci_type": "NONEXISTENT"})
        self.assertEqual(404, _response.status_code)
        _response = self.test_client.get(_url, 
                query_string={"cetype": "NONEXISTENT", "t": None})
        self.assertEqual(400, _response.status_code)

        # test 'all' key
        _url = posixpath.join(posixpath.sep, "versions_by_citype", "all")
        _response = self.test_client.get(_url, 
                query_string={"ci_type": _ci_types_to_check})
        self.assertEqual(200, _response.status_code)
        _prev_response = deepcopy(_response.json)
        _response = self.test_client.get(_url, 
                query_string={"ci_type": _ci_types_to_check})
        self.assertEqual(_prev_response, _response.json)

        for _each_distr in _all_distrs:
            _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"),
                    json=dict((_key, _each_distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _each_distr))
            self.assertEqual(200, _response.status_code)

    # Check parent loop - add of deleted
    def test_check_parent_loop__add(self):
        # add distributive
        _first_distr = self._make_distr_json(1)
        _b_first_distr = self._add_verify_distr(_first_distr)

        # add second and specify first as parent
        _second_distr = self._make_distr_json(2, client="TEST_CLIENT")
        _second_distr["parent"] = [{"checksum": _first_distr.get("checksum")}]
        _b_second_distr = self._add_verify_distr(_second_distr)

        # delete frist
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=
                dict((_key, _first_distr.get(_key)) for _key in ["citype", "version", "client"] if _key in _first_distr))
        self.assertEqual(200, _response.status_code)

        # add first again and specify second as parent
        _first_distr["parent"] = [{"path": _second_distr.get("path")}]
        _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=_first_distr)
        self.assertEqual(409, _response.status_code)

        # add first again and specify itself as parent
        _first_distr["parent"] = [
                dict((_key, _first_distr.get(_key)) 
                    for _key in ["citype", "version", "client"] if _key in _first_distr)]
        _response = self.test_client.post(posixpath.join(posixpath.sep, "add_distributive"), json=_first_distr)
        self.assertEqual(409, _response.status_code)
                

    # check parent loop - update
    def test_check_parent_loop__update(self):
        # add distributive
        _first_distr = self._make_distr_json(1)
        _b_first_distr = self._add_verify_distr(_first_distr)

        # add second and specify first as parent
        _second_distr = self._make_distr_json(2, client="TEST_CLIENT")
        _second_distr["parent"] = [{"path": _first_distr.get("path")}]
        _b_second_distr = self._add_verify_distr(_second_distr)

        # modify first and specify second as parent
        _params = {"checksum": _first_distr.get("checksum"),
                "changes": {"parent":[
                    dict((_key, _second_distr.get(_key)) 
                        for _key in ["citype", "version", "client"] if _key in _second_distr)]}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_params)
        self.assertEqual(409, _response.status_code)

        # modify first and specify itsself as parent
        _params = {"path": _first_distr.get("path"),
                "changes": {"parent":[{"checksum": _first_distr.get("checksum")}]}}
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=_params)
        self.assertEqual(409, _response.status_code)

    # Check deliverability
    def test_artifact_deliverable(self):
        # ask for distr not exist
        _parent = self._make_distr_json(1)
        _response = self.test_client.get(posixpath.join(posixpath.sep, "artifact_deliverable"), json=
                dict((_key, _parent.get(_key)) for _key in ["citype", "version", "client"] if _key in _parent))
        self.assertTrue(_response.json.pop())

        # add distr as deliverable
        _b_parent = self._add_verify_distr(_parent)
        _response = self.test_client.get(posixpath.join(posixpath.sep, "artifact_deliverable"), json=
                {"path": _parent.get("path")})
        self.assertTrue(_response.json.pop())

        # change to not deliverable
        # first assert we are unable do it without comment
        # then add comment and do the same
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=
                {"checksum": _parent.get("checksum"), "changes": 
                {"artifact_deliverable": False}})
        self.assertEqual(400, _response.status_code)
        _response = self.test_client.post(posixpath.join(posixpath.sep, "update_distributive"), json=
                {"checksum": _parent.get("checksum"), "changes": 
                {"artifact_deliverable": False, "commentary": "Test Roach Bug found"}})
        self.assertEqual(201, _response.status_code)
        _response = self.test_client.get(posixpath.join(posixpath.sep, "artifact_deliverable"), json=
                {"path": _parent.get("path")})
        self.assertFalse(_response.json.pop())

        # add second distr and specify first as parent
        _child = self._make_distr_json(2, client="TEST_CLIENT")
        _child["parent"] = [
                dict((_key, _parent.get(_key)) for _key in ["citype", "version", "client"] if _key in _parent)]
        _b_child = self._add_verify_distr(_child)
        self.assertTrue(_b_child.artifact_deliverable)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "artifact_deliverable"), json=
                dict((_key, _child.get(_key)) for _key in ["citype", "version", "client"] if _key in _child))
        self.assertFalse(_response.json.pop())

        # delete first and ask for itself
        _response = self.test_client.delete(posixpath.join(posixpath.sep, "delete_distributive"), json=
                dict((_key, _parent.get(_key)) for _key in ["citype", "version", "client"] if _key in _parent))
        self.assertEqual(200, _response.status_code)

        _response = self.test_client.get(posixpath.join(posixpath.sep, "artifact_deliverable"), json=
                {"checksum": _parent.get("checksum")})
        self.assertFalse(_response.json.pop())

        # ask second - should not be deliverable
        _response = self.test_client.get(posixpath.join(posixpath.sep, "artifact_deliverable"), json=
                {"checksum": _child.get("checksum")})
        self.assertFalse(_response.json.pop())


