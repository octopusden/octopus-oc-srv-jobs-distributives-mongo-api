from mongoengine import *
from datetime import datetime

# MongoEngine does not allow to include "None" values in fields for index based on 'unique_with' constraint
# but we need it for 'client'. Assigning default to empty string then.
class Distributives(Document):
    revision = IntField(default=1)
    timestamp = DateTimeField(default=datetime.now())
    client = StringField(required=True, default="")
    citype = StringField(required=True)
    version = StringField(required=True, unique_with=['client', 'citype'])
    path = ListField(StringField(unique=True, sparse=True), unique=True, sparse=True)
    checksum = ListField(StringField(unique=True, sparse=True), unique=True, sparse=True)
    parent = ListField(ReferenceField('self'))
    artifact_deliverable = BooleanField(default=True)
    commentary = StringField()
    is_actual = BooleanField(default=True)

# History is now mandatory for 'artifact_deliverable' and 'commentary' fields
# Others are out of interest
class DistributivesRevisions(Document):
    revision_of = ReferenceField('Distributives')
    revision = IntField()
    timestamp = DateTimeField(default=datetime.now())
    artifact_deliverable = BooleanField()
    commentary = StringField()
