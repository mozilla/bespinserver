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
import os
from urlparse import urlparse

from dryice.plugins import (Plugin as BasePlugin,
                                 find_plugins as base_find_plugins,
                                 lookup_plugin as base_lookup_plugin)

from bespin import config

class PluginError(Exception):
    pass

class Plugin(BasePlugin):
    def load_metadata(self):
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
            user_location = self.relative_location
            if self.location.isdir():
                user_location += "/"
            md['userLocation'] = user_location
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
    
    return base_find_plugins(search_path, cls=Plugin)

def lookup_plugin(name, search_path=None):
    """Return the plugin descriptor for the plugin given."""
    if search_path is None:
        search_path = config.c.plugin_path
    
    return base_lookup_plugin(name, search_path, cls=Plugin)    

def install_plugin(f, url, settings_project, path_entry, plugin_name=None):
    destination = settings_project.location / "plugins"
    if not destination.exists():
        destination.mkdir()
    
    if plugin_name is None:
        url_parts = urlparse(url)
        filename = os.path.basename(url_parts[2])
        plugin_name = os.path.splitext(filename)[0]
    
    # check for single file plugin
    if url.endswith(".js"):
        destination = destination / (plugin_name + ".js")
        destination.write_bytes(f.read())
    elif url.endswith(".tgz") or url.endswith(".tar.gz"):
        destination = destination / plugin_name
        settings_project.import_tarball(plugin_name + ".tgz", f, 
            "plugins/" + plugin_name + "/")
    elif url.endswith(".zip"):
        destination = destination / plugin_name
        settings_project.import_zipfile(plugin_name + ".zip", f, 
            "plugins/" + plugin_name + "/")
    else:
        raise PluginError("Plugin must be a .js, .zip or .tgz file")
    
    plugin = Plugin(plugin_name, destination, path_entry)
    return plugin
    