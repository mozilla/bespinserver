from datetime import datetime

from sqlalchemy import *
from migrate import *

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (Column, PickleType, String, Integer,
                    Boolean, Binary, Table, ForeignKey,
                    DateTime, func, UniqueConstraint, Text)
from sqlalchemy.orm import relation, deferred, mapper, backref
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import NoResultFound

metadata = MetaData()
metadata.bind = migrate_engine

EventLog = Table('eventlog', metadata, 
    Column('ts', DateTime, default=datetime.now),
    Column('kind', String(10)),
    Column('username', String(128), default=None),
    Column('details', String, default=None),
    mysql_engine='archive'
)

def upgrade():
    # Upgrade operations go here. Don't create your own engine; use the engine
    # named 'migrate_engine' imported from migrate.
    
    # create_all will check for table existence first
    metadata.create_all()
    

def downgrade():
    # Operations to reverse the above upgrade go here.
    
    EventLog.drop(bind=migrate_engine)
