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
    def exists(self):
        return self.location != None
        
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
            if not self.exists:
                md = {}
            else:
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
            if not self.exists:
                scripts = []
            else:
                loc = self.location
                scripts = [loc.relpathto(f) for f in self.location.walkfiles("*.js")]
            self._scripts = scripts
            return scripts
    
    def get_script_text(self, scriptname):
        if not self.exists:
            return None
            
        script_path = self.location / scriptname
        if not script_path.exists():
            return None
        
        return script_path.text()
        
                

def find_plugins(names):
    """Return plugin descriptors for the plugins given in the list 'names'."""
    result = []
    for name in names:
        plugin = Plugin(name)
        result.append(plugin)
        for path in config.c.plugin_path:
            location = path / name
            if location.exists() and location.isdir():
                plugin.location = location
                break
        
    return result
    