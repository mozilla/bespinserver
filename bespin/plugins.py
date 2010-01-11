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

from bespinbuild.plugins import (Plugin as BasePlugin,
                                 find_plugins as base_find_plugins,
                                 lookup_plugin as base_lookup_plugin)

from bespin import config    

class Plugin(BasePlugin):
    def load_metadata(self):
        print "loading metadata for %s from %s" % (self.name, self.location)
        md = super(Plugin, self).load_metadata()
        
        server_base_url = config.c.server_base_url
        if not server_base_url.startswith("/"):
            server_base_url = "/" + server_base_url
        name = self.name
        
        if self.location_name == "user":
            md['scripts'] = [
                dict(url="%sgetscript/file/at/%s%%3A%s" % (
                    server_base_url, self.relative_location, 
                    scriptname),
                    id="%s:%s" % (name, scriptname))
                    for scriptname in self.scripts
                ]
            md['stylesheets'] = [
                dict(url="%sfile/at/%s%%3A%s" % (
                    server_base_url, self.relative_location, 
                    stylesheet),
                    id="%s:%s" % (name, stylesheet))
                for stylesheet in self.stylesheets
            ]
            md["resourceURL"] = "%sfile/at/%s/resources/" % (
                server_base_url, self.relative_location)
        else:
            md['scripts'] = [
                dict(url="%splugin/script/%s/%s/%s" % (
                    server_base_url, self.location_name, 
                    name, scriptname),
                    id="%s:%s" % (name, scriptname))
                    for scriptname in self.scripts
                ]
            md['stylesheets'] = [
                dict(url="%splugin/file/%s/%s/%s" % (
                    server_base_url, self.location_name, name, 
                    stylesheet),
                    id="%s:%s" % (name, stylesheet))
                for stylesheet in self.stylesheets
            ]
            md["resourceURL"] = "%splugin/file/%s/%s/resources/" % (
                server_base_url, self.location_name, name)
        
        md['reloadURL'] = "%splugin/reload/%s" % (
            server_base_url, name)
        
        return md

def find_plugins(search_path=None):
    """Return plugin descriptors for the plugins on the search_path.
    If the search_path is not given, the configured plugin_path will
    be used."""
    if search_path is None:
        search_path = config.c.plugin_path
    
    print "Searching for plugins along: %s" % (search_path)
    
    return base_find_plugins(search_path, cls=Plugin)

def lookup_plugin(name, search_path=None):
    """Return the plugin descriptor for the plugin given."""
    if search_path is None:
        search_path = config.c.plugin_path
    
    return base_lookup_plugin(name, search_path, cls=Plugin)    
