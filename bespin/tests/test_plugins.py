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

from __init__ import BespinTestApp

app = None

def setup_module():
    global app
    config.set_profile('test')
    app = controllers.make_app()
    app = BespinTestApp(app)

    config.c.plugin_path = [(path(__file__).dirname() / "plugindir").abspath()]
    config.c.plugin_default = [p.basename() for p in config.c.plugin_path[0].glob("*")]
    config.activate_profile()

def test_plugin_metadata():
    plugin_list = list(plugins.find_plugins(["plugin1", "plugin2", "plugin3", "NOT THERE"]))
    assert len(plugin_list) == 4
    p = plugin_list[0]
    assert p.name == "plugin1"
    assert p.exists
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
    assert p.exists
    assert not p.errors
    assert not p.depends
    s = p.scripts
    assert len(s) == 1
    assert s == ["mycode.js"]
    
    p = plugin_list[2]
    assert p.name == "plugin3"
    assert p.exists
    assert p.errors[0] == "Problem with metadata JSON: No JSON object could be decoded"
    
    p = plugin_list[3]
    assert p.name == "NOT THERE"
    assert not p.exists
    
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
    
def test_bad_script_request():
    response = app.get("/plugin/script/NOPLUGIN/somefile.js", status=404)
    response = app.get('/plugin/script/../somefile.js', status=400)
    response = app.get('/plugin/script/foo/../bar.js', status=400)
    