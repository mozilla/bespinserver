# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Bespin.
#
# The Initial Developer of the Original Code is
# Mozilla.
# Portions created by the Initial Developer are Copyright (C) 2009
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

import re
import sys

from sqlalchemy import *
from migrate import *

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relation, deferred, mapper, backref

Base = declarative_base()
Base.metadata.bind = migrate_engine

bad_characters = "<>| '\""
invalid_chars = re.compile(r'[%s]' % bad_characters)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    username = Column(String(128), unique=True)
    email = Column(String(128))
    password = Column(String(20))
    settings = Column(PickleType())
    projects = relation('Project', backref='owner')
    quota = Column(Integer, default=10)
    amount_used = Column(Integer, default=0)

usertable = User.__table__

changed_names = dict()

def check_name(new_name):
    result = select([func.count('*')]).where(usertable.c.username==new_name).execute()
    row = result.fetchone()
    return row[0]

def upgrade():
    # Upgrade operations go here. Don't create your own engine; use the engine
    # named 'migrate_engine' imported from migrate.
    for row in select([usertable.c.username]).execute():
        name = row.username
        if invalid_chars.search(name):
            changed_names[name] = invalid_chars.sub("", name)
    for old_name, new_name in changed_names.items():
        if check_name(new_name):
            print "%s is in use for %s" % (new_name, old_name)
            new_name = invalid_chars.sub("-", old_name)
            changed_names[old_name] = new_name
            if check_name(new_name):
                print "EVEN WORSE: %s is in use for %s also" % (new_name, old_name)
                print "Can't continue"
                sys.exit(1)
    for old_name, new_name in changed_names.items():
        update(usertable).where(usertable.c.username==old_name).execute(username=new_name)
    

def downgrade():
    for old_name, new_name in changed_names.items():
        update(usertable).where(usertable.c.username==new_name).execute(username=old_name)
