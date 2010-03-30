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
import re
from urlparse import urlparse
import time

from dryice.plugins import (Plugin as BasePlugin,
                                 find_plugins as base_find_plugins,
                                 lookup_plugin as base_lookup_plugin,
                                 get_metadata)

from bespin import config
from bespin import VERSION
from bespin.database import GalleryPlugin
from bespin.filesystem import NotAuthorized, get_project

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
            version_stamp = int(time.time()) if not "version" in md else md['version']
            md['stylesheets'] = [
                dict(url="%sfile/at/%s%%3A%s?%s" % (
                    server_base_url, self.relative_location, 
                    stylesheet, version_stamp),
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
            
            version_stamp = int(time.time()) if VERSION == "tip" else VERSION
            md['stylesheets'] = [
                dict(url="%splugin/file/%s/%s/%s?%s" % (
                    server_base_url, self.location_name, name, 
                    stylesheet, version_stamp),
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
    
    

# Plugin Gallery functionality

_required_fields = set(["name", "description", "version", "licenses"])
_upper_case = re.compile("[A-Z]")
_beginning_letter = re.compile("^[a-zA-Z]")
_illegal_characters = re.compile(r"[^\w\._\-]")
_semver1 = re.compile(r"^\d+[A-Za-z0-9\-]*$")
_semver2 = re.compile(r"^\d+\.\d+[A-Za-z0-9\-]*$")
_semver3 = re.compile(r"^\d+\.\d+\.\d+[A-Za-z0-9\-]*$")

def _validate_version_string(version):
    if  not _semver1.match(version) and not _semver2.match(version) \
        and not _semver3.match(version):
        return False
    return True

def _validate_metadata(metadata):
    """Ensures that plugin metadata is valid for inclusion in the
    Gallery."""
    errors = set([])
    for field in _required_fields:
        if field not in metadata:
            errors.add("%s is required" % (field))

    try:
        name = metadata['name']
        if _upper_case.search(name):
            errors.add("name must be lower case")
        if not _beginning_letter.search(name):
            errors.add("name must begin with a letter")
        if _illegal_characters.search(name):
            errors.add("name may only contain letters, numbers, '.', '_' and '-'")
    except KeyError:
        pass
    
    try:
        version = metadata['version']
        if not _validate_version_string(version):
            errors.add("version should be of the form X(.Y)(.Z)(alpha/beta/etc) http://semver.org")
    except KeyError:
        pass
    
    try:
        keywords = metadata['keywords']
        if not isinstance(keywords, list):
            errors.add("keywords should be an array of strings")
        else:
            for kw in keywords:
                if not isinstance(kw, basestring):
                    errors.add("keywords should be an array of strings")
                    break
    except KeyError:
        pass
    
    try:
        licenses = metadata['licenses']
        if not isinstance(licenses, list):
            errors.add("licenses should be an array of objects http://semver.org")
        else:
            for l in licenses:
                if not isinstance(l, dict):
                    errors.add("licenses should be an array of objects http://semver.org")
                    break
    except KeyError:
        pass
    
    if "depends" in metadata:
        errors.add("'depends' is not longer supported. use dependencies.")
    
    try:
        dependencies = metadata['dependencies']
        if not isinstance(dependencies, dict):
            errors.add('dependencies should be a dictionary')
        else:
            for dependName, info in dependencies.items():
                if isinstance(info, basestring):
                    if not _validate_version_string(info):
                        errors.add("'%s' is not a valid version for dependency '%s'" 
                                   % (info, dependName))
                elif isinstance(info, list):
                    for v in info:
                        if not _validate_version_string(v):
                            errors.add("'%s' is not a valid version for dependency '%s'" 
                                       % (v, dependName))
                else:
                    errors.add("'%s' is not a valid version for dependency '%s'"
                               % (info, dependName))
                            
    except KeyError:
        pass
        
    return errors

def save_to_gallery(user, location):
    """This is how a new plugin or new version of a plugin gets into the
    gallery. Note that any errors will result in a PluginError exception
    being raised."""
    metadata, errors = get_metadata(location)
    if errors:
        raise PluginError("Errors found when reading plugin metadata: %s" % (errors,))
    
    errors = _validate_metadata(metadata)
    if errors:
        raise PluginError("Errors in plugin metadata: %s" % (errors,))
    
    plugin = GalleryPlugin.get_plugin(metadata['name'], user, create=True)
    if plugin.owner_id != user.id:
        raise NotAuthorized("Plugin '%s' is owned by another user" % (metadata['name']))
    
    gallery_root = config.c.gallery_root
    plugin_dir = gallery_root / metadata['name']
    if not plugin_dir.exists():
        plugin_dir.makedirs()
    
    if location.isdir():
        destination = plugin_dir / metadata['version']
        if destination.exists():
            raise PluginError("%s version %s already exists" % (metadata['name'],
                                                                metadata['version']))
        location.copytree(destination)
    else:
        destination = plugin_dir / (metadata['version'] + ".js")
        if destination.exists():
            raise PluginError("%s version %s already exists" % (metadata['name'],
                                                                metadata['version']))
        location.copy(destination)
    
    if not plugin.version:
        plugin.version = metadata['version']
        plugin.package_info = metadata

def _collect_dependencies(main_plugin):
    result = dict()
    def add_deps(plugin):
        deps = plugin.package_info.get("dependencies")
        if not deps:
            return
        for dep in deps:
            if dep in result:
                continue
            dep_plugin = GalleryPlugin.get_plugin(dep)
            if not dep_plugin:
                raise PluginError("Cannot find dependency '%s' for plugin '%s'"
                                  % (dep, plugin.name))
            result[dep] = dep_plugin
            add_deps(dep_plugin)
    add_deps(main_plugin)
    return result

def _perform_installation(user, plugin):
    version = plugin.version
    gallery_root = config.c.gallery_root
    plugin_dir = gallery_root / plugin.name
    
    location = plugin_dir / version
    if not location.exists():
        location = plugin_dir / (version + ".js")
        if not location.exists():
            raise PluginError("Unable to find the plugin files for '%s' version %s"
                % (plugin_name, plugin.version))
    
    project = get_project(user, user, "BespinSettings")
    
    if location.isdir():
        destination = project.location / "plugins" / plugin.name
        if destination.exists():
            destination.rmtree()
        location.copytree(destination)
    else:
        destination = project.location / "plugins" / (plugin.name + ".js")
        if destination.exists():
            destination.unlink()
        location.copy(destination)
    

def install_plugin_from_gallery(user, plugin_name):
    plugin = GalleryPlugin.get_plugin(plugin_name)
    if not plugin:
        raise PluginError('Cannot find plugin "%s" in the gallery' % (plugin_name))
    
    deps = _collect_dependencies(plugin)
    
    deps[plugin.name] = plugin
    
    for dep in deps.values():
        _perform_installation(user, dep)
    
    return dict((plugin.name, plugin.package_info) for plugin in deps.values())
    