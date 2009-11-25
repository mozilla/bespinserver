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

from simplejson import loads

from bespin import config

class Plugin(object):
    def __init__(self, name):
        self.name = name
        self._errors = []
        self.location = None
    
    @property
    def errors(self):
        md = self.metadata
        return self._errors
    
    @property
    def depends(self):
        md = self.metadata
        if md:
            return md.get('depends', [])
        return []
    
    @property
    def metadata(self):
        try:
            return self._metadata
        except AttributeError:
            md_path = self.location / "plugin.json"
            if not md_path.exists():
                md = {}
                self._errors = ["Plugin metadata file (plugin.json) file is missing"]
            else:
                md_text = md_path.text()
                try:
                    md = loads(md_text)
                except Exception, e:
                    self._errors = ["Problem with metadata JSON: %s" % (e)]
                    md = {}
            self._metadata = md
            return md
            
    @property
    def scripts(self):
        try:
            return self._scripts
        except AttributeError:
            loc = self.location
            scripts = [loc.relpathto(f) for f in self.location.walkfiles("*.js")]
            self._scripts = scripts
            return scripts
    
    def get_script_text(self, scriptname):
        """Look up the script at scriptname within this plugin."""
        script_path = self.location / scriptname
        if not script_path.exists():
            return None
        
        return script_path.text()
        
                

def find_plugins(search_path=None):
    """Return plugin descriptors for the plugins on the search_path.
    If the search_path is not given, the configured plugin_path will
    be used."""
    if search_path is None:
        search_path = config.c.plugin_path
        
    result = []
    for path in search_path:
        for name in path.glob("*"):
            name = name.basename()
            plugin = Plugin(name)
            result.append(plugin)
            plugin.location = path / name
    return result
    
def lookup_plugin(name, search_path=None):
    """Return the plugin descriptor for the plugin given."""
    if search_path is None:
        search_path = config.c.plugin_path
        
    for path in search_path:
        location = path / name
        if location.exists():
            plugin = Plugin(name)
            plugin.location = location
            return plugin
    
    return None