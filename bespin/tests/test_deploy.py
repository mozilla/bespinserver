#  ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1
# 
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
# 
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the License.
# 
# The Original Code is Bespin.
# 
# The Initial Developer of the Original Code is Mozilla.
# Portions created by the Initial Developer are Copyright (C) 2009
# the Initial Developer. All Rights Reserved.
# 
# Contributor(s):
# 
# ***** END LICENSE BLOCK *****
# 

import logging
from path import path
from simplejson import dumps, loads

from bespin.database import Base
from bespin.database import User
from bespin import deploy, config, controllers
from bespin.filesystem import get_project, NotAuthorized

from bespin.tests import BespinTestApp
from bespin.tests.mock import patch

app = None

def setup_module(module):
    global app
    config.set_profile('test')
    app = controllers.make_app()
    app = BespinTestApp(app)
    logging.basicConfig(level=logging.DEBUG)
    
def _init_data():
    global macgyver
    config.activate_profile()
    
    fsroot = config.c.fsroot
    if fsroot.exists() and fsroot.basename() == "testfiles":
        fsroot.rmtree()
    fsroot.makedirs()
    
    app.reset()
    
    Base.metadata.drop_all(bind=config.c.dbengine)
    Base.metadata.create_all(bind=config.c.dbengine)
    s = config.c.session_factory()
    
    app.post("/register/new/MacGyver", 
        dict(password="richarddean", email="rich@sg1.com"))
        
    macgyver = User.find_user("MacGyver")
    s.flush()



def test_keychain_creation():
    _init_data()
    kc = deploy.DeploymentKeyChain(macgyver, "foobar")
    public_key, private_key = kc.get_ssh_key()
    
    assert public_key.startswith("ssh-rsa")
    assert "RSA PRIVATE KEY" in private_key
    
    public_key2 = deploy.DeploymentKeyChain.get_ssh_public_key(macgyver)
    assert public_key2 == public_key
    
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    
    kc.set_ssh_for_project(bigmac, "macgyver")
    
    kcfile = path(macgyver.get_location()) / ".bespin-keychain"
    assert kcfile.exists()
    
    # make sure the file is encrypted
    text = kcfile.bytes()
    assert "RSA PRIVATE KEY" not in text
    assert "ssh-rsa" not in text
    
    kc = deploy.DeploymentKeyChain(macgyver, "foobar")
    public_key2, private_key2 = kc.get_ssh_key()
    assert public_key2 == public_key
    assert private_key2 == private_key
    
    credentials = kc.get_credentials_for_project(bigmac)
    assert "RSA PRIVATE KEY" in credentials['ssh_private_key']
    assert credentials['type'] == "ssh"
    assert credentials['username'] == 'macgyver'
    
    kc.delete_credentials_for_project(bigmac)
    credentials = kc.get_credentials_for_project(bigmac)
    assert credentials is None
    
    kc.set_credentials_for_project(bigmac, "macG", "coolpass")
    
    kc = deploy.DeploymentKeyChain(macgyver, "foobar")
    credentials = kc.get_credentials_for_project(bigmac)
    assert credentials['type'] == 'password'
    assert credentials['username'] == 'macG'
    assert credentials['password'] == 'coolpass'
    
    kc.delete_credentials_for_project(bigmac)
    
    kc = deploy.DeploymentKeyChain(macgyver, "foobar")
    credentials = kc.get_credentials_for_project(bigmac)
    assert credentials is None

def test_set_project_deployment_metadata():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    pdo = deploy.ProjectDeploymentOptions(bigmac,
        remote_host="macgyver.com",
        remote_directory="/home/macgyver/knownunknowns",
        type="sftp")
    pdo.save()
    
    md = bigmac.metadata
    options_json = md['deployment']
    assert "remote_host" in options_json
    assert "sftp" in options_json
    
    pdo = deploy.ProjectDeploymentOptions.get(bigmac)
    assert pdo.remote_host == "macgyver.com"
    assert pdo.remote_directory == "/home/macgyver/knownunknowns"
    
# Web tests

def test_deployment_setup():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    resp = app.put("/project/deploy/bigmac/setup", dumps(dict(
        remoteHost="macgyver.com",
        remoteDirectory="/home/macgyver/knownunknowns",
        connType="sftp",
        kcpass="sekretkeychain",
        authType="ssh",
        username="macman")))
    
    bigmac = get_project(macgyver, macgyver, "bigmac")
    pdo = deploy.ProjectDeploymentOptions.get(bigmac)
    assert pdo.remote_host == "macgyver.com"
    assert pdo.remote_directory == "/home/macgyver/knownunknowns"
    kc = deploy.DeploymentKeyChain(macgyver, "sekretkeychain")
    cred = kc.get_credentials_for_project(bigmac)
    assert cred['type'] == "ssh"
    assert cred["username"] == "macman"
    
    resp = app.post("/project/deploy/bigmac/setup", 
        dumps(dict(kcpass="sekretkeychain")))
    assert resp.content_type == "application/json"
    data = loads(resp.body)
    assert data['authType'] == "ssh"
    assert data['username'] == "macman"
    assert data['remoteHost'] == "macgyver.com"
    assert data['remoteDirectory'] == "/home/macgyver/knownunknowns"
    assert data['connType'] == "sftp"

    resp = app.put("/project/deploy/bigmac/setup", dumps(dict(
        remoteHost="macgyver.com",
        remoteDirectory="/home/macgyver/knownunknowns",
        connType="sftp",
        kcpass="sekretkeychain",
        authType="password",
        username="macman",
        password="NO ONE WILL EVER GUESS THIS!")))
    
    resp = app.post("/project/deploy/bigmac/setup", 
        dumps(dict(kcpass="sekretkeychain")))
    assert resp.content_type == "application/json"
    data = loads(resp.body)
    assert data['authType'] == "password"
    assert data['username'] == "macman"
    assert data['password'] == "NO ONE WILL EVER GUESS THIS!"
    assert data['remoteHost'] == "macgyver.com"
    assert data['remoteDirectory'] == "/home/macgyver/knownunknowns"
    assert data['connType'] == "sftp"

def test_retrieve_new_deployment_setup():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    resp = app.post("/project/deploy/bigmac/setup", 
        dumps(dict(kcpass="sekretkeychain")))
    assert resp.content_type == "application/json"
    data = loads(resp.body)
    assert data is None
    
def test_deployment_fails_when_not_configured():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    resp = app.post("/project/deploy/bigmac/", 
        dumps(dict(kcpass="sekretkeychain")), status=400)
    assert resp.content_type == "application/json"
    data = loads(resp.body)
    assert data['error'] == "Deployment is not yet configured."
    assert data['notConfigured'] == True
    
def test_deployment_setup_with_illegal_parameters():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    resp = app.put("/project/deploy/bigmac/setup", dumps(dict(
        remoteHost="macgyver.com",
        remoteDirectory="/home/macgyver/knownunknowns",
        connType="file",
        kcpass="sekretkeychain",
        authType="ssh",
        username="macman")), status=400)
    
    
@patch("bespin.deploy._launch_sync")
def test_deployment_runs(launch_sync):
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    resp = app.put("/project/deploy/bigmac/setup", dumps(dict(
        remoteHost="macgyver.com",
        remoteDirectory="/home/macgyver/knownunknowns",
        connType="sftp",
        kcpass="sekretkeychain",
        authType="password",
        username="macman",
        password="super/pass")))

    resp = app.post("/project/deploy/bigmac/", 
        dumps(dict(kcpass="sekretkeychain", dryRun=True)))
    
    assert resp.content_type == "application/json"
    data = loads(resp.body)
    
    assert 'jobid' in data
    assert data['jobid'] is not None
    assert launch_sync.called
    desturl = launch_sync.call_args[0][2]
    assert desturl == "sftp://macgyver.com//home/macgyver/knownunknowns"
    options = launch_sync.call_args[0][3]
    assert options.dry_run
    assert options.username == "macman"
    assert options.password == "super/pass"
    
@patch("bespin.deploy._launch_sync")
def test_deployment_runs_with_ssh_key(launch_sync):
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    resp = app.put("/project/deploy/bigmac/setup", dumps(dict(
        remoteHost="macgyver.com",
        remoteDirectory="/home/macgyver/knownunknowns",
        connType="sftp",
        kcpass="sekretkeychain",
        authType="ssh",
        username="macman")))

    resp = app.post("/project/deploy/bigmac/", 
        dumps(dict(kcpass="sekretkeychain")))
    
    assert resp.content_type == "application/json"
    data = loads(resp.body)
    
    assert 'jobid' in data
    assert data['jobid'] is not None
    assert launch_sync.called
    desturl = launch_sync.call_args[0][2]
    assert desturl == "sftp://macgyver.com//home/macgyver/knownunknowns"
    options = launch_sync.call_args[0][3]
    assert not options.dry_run
    assert options.username == "macman"
    assert isinstance(options.sshkey, path)
    assert not options.sshkey.exists(), "Key file should be deleted at the end"
    
    