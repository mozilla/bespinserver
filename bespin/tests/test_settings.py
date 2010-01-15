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
# 

from __init__ import BespinTestApp
import simplejson

from bespin import config, controllers
from bespin.database import User, Base

app = None
session = None

def setup_module(module):
    global app, session
    config.set_profile('test')
    config.activate_profile()
    Base.metadata.drop_all(bind=config.c.dbengine)
    Base.metadata.create_all(bind=config.c.dbengine)
    session = config.c.session_factory()
    User.create_user("BillBixby", "", "bill@bixby.com")
    app = controllers.make_app()
    app = BespinTestApp(app)
    app.post("/register/login/BillBixby", dict(password=""))

def test_auth_required():
    app = controllers.make_app()
    app = BespinTestApp(app)
    app.post('/settings/', {'foo' : 'bar'}, status=401)
    app.get('/settings/', status=401)
    app.get('/settings/foo', status=401)

def test_set_settings():
    resp = app.post('/settings/', {'antigravity' : 'on', 'write_my_code' : 'on'})
    assert not resp.body
    user = User.find_user('BillBixby')
    session.expunge(user)
    user = User.find_user('BillBixby')
    assert user.settings['antigravity'] == 'on'
    assert user.settings['write_my_code'] == 'on'
    
    resp = app.get('/settings/')
    assert resp.content_type == 'application/json'
    data = simplejson.loads(resp.body)
    assert data == {'antigravity' : 'on', 'write_my_code' : 'on'}
    
    resp = app.get('/settings/antigravity')
    assert resp.content_type == "application/json"
    assert resp.body == '"on"'

def test_non_existent_setting_sends_404():
    resp = app.get('/settings/BADONE', status=404)
    
def test_delete_setting():
    resp = app.post('/settings/', {'newone' : 'hi there'})
    resp = app.delete('/settings/newone')
    user = User.find_user('BillBixby')
    session.expunge(user)
    user = User.find_user('BillBixby')
    assert 'newone' not in user.settings
    