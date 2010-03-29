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
Base = declarative_base(metadata=metadata)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True)
    username = Column(String(128), unique=True)
    email = Column(String(128))
    password = Column(String(64))
    settings = Column(PickleType())
    quota = Column(Integer, default=10)
    amount_used = Column(Integer, default=0)
    file_location = Column(String(200))
    everyone_viewable = Column(Boolean, default=False)

class Gallery(Base):
    """Plugin Gallery entries"""
    __tablename__ = "gallery"
    
    id = Column(Integer, primary_key=True)
    owner_id=Column(Integer, ForeignKey('users.id', ondelete="cascade"))
    name=Column(String(128))
    version=Column(String(30))
    packageInfo=Column(PickleType())

def upgrade():
    # Upgrade operations go here. Don't create your own engine; use the engine
    # named 'migrate_engine' imported from migrate.
    
    # create_all will check for table existence first
    metadata.create_all()
    

def downgrade():
    # Operations to reverse the above upgrade go here.
    
    Gallery.__table__.drop(bind=migrate_engine)
