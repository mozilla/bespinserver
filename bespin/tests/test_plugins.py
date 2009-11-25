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

from path import path

from bespin import config, plugins, controllers
from bespin.database import User, Base

from __init__ import BespinTestApp

app = None

plugindir = (path(__file__).dirname() / "plugindir").abspath()

def setup_module():
    global app
    config.set_profile('test')
    app = controllers.make_app()
    app = BespinTestApp(app)

    config.c.plugin_path = [plugindir]
    config.activate_profile()

def _init_data():
    global macgyver, someone_else, murdoc
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


def test_plugin_metadata():
    plugin_list = list(plugins.find_plugins())
    assert len(plugin_list) == 5
    p = plugin_list[0]
    assert p.name == "plugin1"
    assert not p.errors
    assert p.depends[0] == "plugin2"
    s = p.scripts
    assert len(s) == 2
    assert "thecode.js" in s
    assert "subdir/morecode.js" in s
    text = p.get_script_text("thecode.js")
    assert "this is the code" in text
    
    p = plugin_list[1]
    assert p.name == "plugin2"
    assert not p.errors
    assert not p.depends
    s = p.scripts
    assert len(s) == 1
    assert s == ["mycode.js"]
    
    p = plugin_list[2]
    assert p.name == "plugin3"
    assert p.errors[0] == "Problem with metadata JSON: No JSON object could be decoded"
    
    p = plugin_list[3]
    assert p.name == "SingleFilePlugin1"
    errors = p.errors
    assert errors == []
    s = p.scripts
    assert s == [""]
    script_text = p.get_script_text("")
    assert "exports.someFunction" in script_text
    
    p = plugin_list[4]
    assert p.name == "SingleFilePlugin2"
    errors = p.errors
    assert errors

def test_lookup_plugin():
    plugin = plugins.lookup_plugin("DOES NOT EXIST")
    assert plugin is None
    plugin = plugins.lookup_plugin("plugin1")
    assert not plugin.errors
    plugin = plugins.lookup_plugin("SingleFilePlugin1")
    assert not plugin.errors
    
# Web tests

def test_default_plugin_registration():
    response = app.get("/plugin/register/defaults")
    assert response.content_type == "text/javascript"
    assert "plugin1" in response.body
    assert "NOT THERE" not in response.body
    assert "plugin3" not in response.body
    
def test_get_script_from_plugin():
    response = app.get("/plugin/script/plugin1/thecode.js")
    content_type = response.content_type
    assert content_type == "text/javascript"
    assert "this is the code" in response.body

def test_get_single_file_script():
    response = app.get("/plugin/script/SingleFilePlugin1/")
    content_type = response.content_type
    assert content_type == "text/javascript"
    assert "exports.someFunction" in response.body
    assert "SingleFilePlugin1:package" in response.body
    
    
def test_bad_script_request():
    response = app.get("/plugin/script/NOPLUGIN/somefile.js", status=404)
    response = app.get('/plugin/script/../somefile.js', status=400)
    response = app.get('/plugin/script/foo/../bar.js', status=400)
    
def test_user_installed_plugins():
    _init_data()
    sfp = (path(__file__).dirname() / "plugindir").abspath() / "SingleFilePlugin1.js"
    sfp_content = sfp.text()
    response = app.put("/file/at/BespinSettings/plugins/MyPlugin.js", sfp_content)
    response = app.put("/file/at/BespinSettings/plugins/BiggerPlugin/plugin.json", "{}");
    response = app.get("/plugin/register/user")
    assert response.content_type == "text/javascript"
    assert "MyPlugin" in response.body
    assert "BiggerPlugin" in response.body
    assert "EditablePlugin" not in response.body
    
    response = app.put("/file/at/myplugins/EditablePlugin/plugin.json", "{}")
    response = app.put("/file/at/BespinSettings/pluginInfo.json", """{
"path": ["myplugins/"],
"pluginOrdering": ["EditablePlugin"]
}""")
    response = app.get("/plugin/register/user")
    assert response.content_type == "text/javascript"
    print response.body[:200]
    assert "MyPlugin" in response.body
    assert "BiggerPlugin" in response.body
    assert "EditablePlugin" in response.body
    