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

from simplejson import loads

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

    config.c.plugin_path = [dict(name="testplugins", path=plugindir, chop=len(plugindir))]
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

def test_plugin_metadata_parsing():
    tests = [
        ["""

"define metadata";
({"foo": "bar"});
"end";

More code here...

""", dict(foo="bar")]
    ]
    
    def run_one(input, expected):
        md_text = plugins._parse_md_text(input.split("\n"))
        print md_text
        if expected is None:
            assert md_text is None
        else:
            assert md_text
            parsed = loads(md_text)
            assert parsed == expected
    
    for test in tests:
        run_one(*test)

def test_plugin_metadata():
    plugin_list = list(plugins.find_plugins())
    assert len(plugin_list) == 5
    p = plugin_list[0]
    assert p.name == "plugin1"
    assert p.location_name == "testplugins"
    assert p.relative_location == "plugin1"
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
    assert p.location_name == "testplugins"
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

def test_plugin_stylesheets():
    plugin = plugins.lookup_plugin("plugin1")
    assert plugin.stylesheets == ["resources/foo/foo.css"]
    plugin = plugins.lookup_plugin("plugin2")
    assert plugin.stylesheets == []
    plugin = plugins.lookup_plugin("SingleFilePlugin1")
    assert plugin.stylesheets == []
    

def test_lookup_plugin():
    plugin = plugins.lookup_plugin("DOES NOT EXIST")
    assert plugin is None
    plugin = plugins.lookup_plugin("plugin1")
    assert not plugin.errors
    assert plugin.location_name == "testplugins"
    plugin = plugins.lookup_plugin("SingleFilePlugin1")
    assert not plugin.errors
    
# Web tests

def test_default_plugin_registration():
    response = app.get("/plugin/register/defaults")
    assert response.content_type == "text/javascript"
    assert "plugin1" in response.body
    assert "plugin/script/testplugins/plugin1/thecode.js" in response.body
    assert "plugin/file/testplugins/plugin1/resources/foo/foo.css" in response.body
    assert "NOT THERE" not in response.body
    assert "plugin3" not in response.body
    
def test_get_script_from_plugin():
    response = app.get("/plugin/script/testplugins/plugin1/thecode.js")
    content_type = response.content_type
    assert content_type == "text/javascript"
    assert "this is the code" in response.body
    
def test_get_script_bad_plugin_location():
    response = app.get("/plugin/script/BOGUSLOCATION/plugin1/thecode.js",
        status=404)

def test_get_single_file_script():
    response = app.get("/plugin/script/testplugins/SingleFilePlugin1/")
    content_type = response.content_type
    assert content_type == "text/javascript"
    assert "exports.someFunction" in response.body
    assert "SingleFilePlugin1:index" in response.body
    
def test_get_stylesheet():
    response = app.get("/plugin/file/testplugins/plugin1/resources/foo/foo.css")
    content_type = response.content_type
    assert content_type == "text/css"
    assert "body {}" in response.body
    
    
def test_bad_script_request():
    response = app.get("/plugin/script/testplugins/NOPLUGIN/somefile.js", status=404)
    response = app.get('/plugin/script/testplugins/../somefile.js', status=400)
    response = app.get('/plugin/script/testplugins/foo/../bar.js', status=400)
    
def test_user_installed_plugins():
    _init_data()
    sfp = (path(__file__).dirname() / "plugindir").abspath() / "SingleFilePlugin1.js"
    sfp_content = sfp.text()
    response = app.put("/file/at/BespinSettings/plugins/MyPlugin.js", sfp_content)
    response = app.put("/file/at/BespinSettings/plugins/BiggerPlugin/plugin.json", "{}");
    response = app.put("/file/at/BespinSettings/plugins/BiggerPlugin/somedir/script.js", 
        "exports.foo = 1;\n")
    response = app.get("/plugin/register/user")
    assert response.content_type == "text/javascript"
    assert "MyPlugin" in response.body
    assert "BiggerPlugin" in response.body
    assert "file/at/BespinSettings/plugins/MyPlugin.js%3A" in response.body
    assert "EditablePlugin" not in response.body
    assert "file/at/BespinSettings/plugins/BiggerPlugin%3Asomedir/script.js" in response.body
    
    response = app.put("/file/at/myplugins/EditablePlugin/plugin.json", "{}")
    response = app.put("/file/at/BespinSettings/pluginInfo.json", """{
"path": ["myplugins/"],
"pluginOrdering": ["EditablePlugin"]
}""")
    response = app.get("/plugin/register/user")
    assert response.content_type == "text/javascript"
    assert "MyPlugin" in response.body
    assert "BiggerPlugin" in response.body
    assert "EditablePlugin" in response.body
    
    response = app.get("/getscript/file/at/BespinSettings/plugins/MyPlugin.js%3A")
    assert response.content_type == "text/javascript"
    assert "someFunction" in response.body
    assert "tiki.module('MyPlugin:index', function" in response.body
    
    response = app.get("/getscript/file/at/BespinSettings/plugins/BiggerPlugin%3Asomedir/script.js")
    assert "tiki.module('BiggerPlugin:somedir/script', function" in response.body
    assert "tiki.script('BiggerPlugin:somedir/script.js')" in response.body
    
    
def test_plugin_reload():
    _init_data()
    response = app.get("/plugin/reload/plugin2")
    print response.body
    assert '"plugin2": {}' in response.body
    # just need the plugin, not its dependents
    assert '"depends": ["plugin2"]' not in response.body
    