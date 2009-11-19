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

from bespin import config, plugins

def setup_module():
    config.set_profile("test")
    config.c.plugin_path = [(path(__file__).dirname() / "plugindir").abspath()]
    config.activate_profile()

def test_plugin_metadata():
    plugin_list = list(plugins.find_plugins(["plugin1", "plugin2", "plugin3", "NOT THERE"]))
    assert len(plugin_list) == 4
    p = plugin_list[0]
    assert p.name == "plugin1"
    assert p.exists
    assert not p.errors
    assert p.depends[0] == "plugin2"
    
    p = plugin_list[1]
    assert p.name == "plugin2"
    assert p.exists
    assert not p.errors
    assert not p.depends
    
    p = plugin_list[2]
    assert p.name == "plugin3"
    assert p.exists
    assert p.errors[0] == "Problem with metadata JSON: No JSON object could be decoded"
    
    p = plugin_list[3]
    assert p.name == "NOT THERE"
    assert not p.exists
    