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

from path import path

from simplejson import loads

from bespin import config, plugins, controllers
from bespin.database import User, Base, EventLog, _get_session, GalleryPlugin
from bespin.filesystem import get_project

from __init__ import BespinTestApp

app = None

plugindir = (path(__file__).dirname() / "plugindir").abspath()

def setup_module():
    global app, app_murdoc
    config.set_profile('test')
    app = controllers.make_app()
    app = BespinTestApp(app)
    app_murdoc = controllers.make_app()
    app_murdoc = BespinTestApp(app_murdoc)
    

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
        
    app_murdoc.post("/register/new/Murdoc", 
        dict(password="murdoc", email="murdoc@badpeople.bad"))

    macgyver = User.find_user("MacGyver")
    
def test_install_single_file_plugin():
    _init_data()
    settings_project = get_project(macgyver, macgyver, "BespinSettings")
    destination = settings_project.location / "plugins"
    path_entry = dict(chop=len(macgyver.get_location()), name="user")
    sfp = plugindir / "SingleFilePlugin1.js"
    plugin = plugins.install_plugin(open(sfp), "http://somewhere/file.js", 
                                    settings_project, path_entry, "APlugin")
    destfile = destination / "APlugin.js"
    assert destfile.exists()
    desttext = destfile.text()
    assert "someFunction" in desttext
    assert plugin.name == "APlugin"
    assert plugin.location == destfile
    assert plugin.relative_location == "BespinSettings/plugins/APlugin.js"
    metadata = plugin.metadata
    type = metadata['type']
    assert type == "user"
    assert metadata['userLocation'] == "BespinSettings/plugins/APlugin.js"
    
    plugin = plugins.install_plugin(open(sfp), "http://somewhere/Flibber.js",
                                    settings_project, path_entry)
    destfile = destination / "Flibber.js"
    assert destfile.exists()
    assert plugin.name == "Flibber"
    
def test_install_tarball_plugin():
    _init_data()
    settings_project = get_project(macgyver, macgyver, "BespinSettings")
    destination = settings_project.location / "plugins"
    path_entry = dict(chop=len(macgyver.get_location()), name="user")
    mfp = path(__file__).dirname() / "plugin1.tgz"
    plugin = plugins.install_plugin(open(mfp), "http://somewhere/file.tgz", 
                                    settings_project, path_entry, "APlugin")
    
    plugin_info = destination / "APlugin" / "package.json"
    assert plugin_info.exists()
    dep = plugin.metadata['dependencies']
    assert dep['plugin2'] == '0.0'
    user_location = plugin.metadata['userLocation']
    assert user_location == "BespinSettings/plugins/APlugin/"
    
def test_install_zipfile_plugin():
    _init_data()
    settings_project = get_project(macgyver, macgyver, "BespinSettings")
    destination = settings_project.location / "plugins"
    path_entry = dict(chop=len(macgyver.get_location()), name="user")
    mfp = path(__file__).dirname() / "plugin1.zip"
    plugin = plugins.install_plugin(open(mfp), "http://somewhere/file.zip", 
                                    settings_project, path_entry, "APlugin")
    
    plugin_info = destination / "APlugin" / "package.json"
    assert plugin_info.exists()
    dep = plugin.metadata['dependencies']
    assert dep['plugin2'] == '0.0'
    
# Web tests

def test_default_plugin_registration():
    response = app.get("/plugin/register/defaults")
    assert response.content_type == "application/json"
    print response.body
    assert "plugin1" in response.body
    assert "plugin/script/testplugins/plugin1/thecode.js" in response.body
    assert "plugin/file/testplugins/plugin1/resources/foo/foo.css" in response.body
    assert "NOT THERE" not in response.body
    data = loads(response.body)
    md = data["plugin1"]
    assert "errors" not in md
    assert md["resourceURL"] == "/server/plugin/file/testplugins/plugin1/resources/"
    assert "plugin3" in data
    md = data['plugin3']
    assert "errors" in md
    
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
    response = app.put("/file/at/BespinSettings/plugins/BiggerPlugin/package.json", "{}");
    response = app.put("/file/at/BespinSettings/plugins/BiggerPlugin/somedir/script.js", 
        "exports.foo = 1;\n")
    response = app.get("/plugin/register/user")
    assert response.content_type == "application/json"
    assert "MyPlugin" in response.body
    assert "BiggerPlugin" in response.body
    assert "file/at/BespinSettings/plugins/MyPlugin.js%3A" in response.body
    assert "EditablePlugin" not in response.body
    assert "file/at/BespinSettings/plugins/BiggerPlugin%3Asomedir/script.js" in response.body
    data = loads(response.body)
    md = data["BiggerPlugin"]
    assert md["resourceURL"] == "/server/file/at/BespinSettings/plugins/BiggerPlugin/resources/"
    
    response = app.put("/file/at/myplugins/EditablePlugin/package.json", "{}")
    response = app.put("/file/at/BespinSettings/pluginInfo.json", """{
"path": ["myplugins/"],
"pluginOrdering": ["EditablePlugin"]
}""")
    response = app.get("/plugin/register/user")
    assert response.content_type == "application/json"
    assert "MyPlugin" in response.body
    assert "BiggerPlugin" in response.body
    assert "EditablePlugin" in response.body
    
    data = loads(response.body)
    assert len(data) == 3
    s = _get_session()
    sel = EventLog.select().where(EventLog.c.kind=='userplugin')
    result = s.connection().execute(sel).fetchall()
    assert len(result) == 2
    assert result[-1].details == '3'
    
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
    assert '"plugin2": {' in response.body
    # just need the plugin, not its dependents
    assert '"dependencies": {"plugin2": "0.0"}' not in response.body

good_metadata = dict(
    name="foo9.27_bar",
    description="Bar. Baz bing!",
    version="1.0",
    licenses=[dict(url="http://bar")]
)

def test_plugin_metadata_validation():
    vm = plugins._validate_metadata
    result = vm({})
    assert "name is required" in result
    assert "description is required" in result
    assert "version is required" in result
    assert "licenses is required" in result
    
    result = vm(good_metadata)
    assert result == set()
    
    data = dict(good_metadata)
    data['name'] = "FOO"
    result = vm(data)
    assert result == set(["name must be lower case"])
    
    data['name'] = "9foo"
    result = vm(data)
    assert result == set(["name must begin with a letter"])
    
    data['name'] = "foo bar"
    result = vm(data)
    assert result == set(["name may only contain letters, numbers, '.', '_' and '-'"])
    
    data = dict(good_metadata)
    data['version'] = "hi there"
    result = vm(data)
    assert result == set(["version should be of the form X(.Y)(.Z)(alpha/beta/etc) http://semver.org"])
    
    data['version'] = "1"
    result = vm(data)
    assert result == set()
    
    data['version'] = "1.0beta"
    result = vm(data)
    assert result == set()
    
    data['version'] = "1.0.1alpha2"
    result = vm(data)
    assert result == set()
    
    data['version'] = "1.0.1not valid"
    result = vm(data)
    assert result == set(["version should be of the form X(.Y)(.Z)(alpha/beta/etc) http://semver.org"])
    
    data = dict(good_metadata)
    data['keywords'] = ["this", "is", "a", "good", "one"]
    result = vm(data)
    assert result == set()
    
    data['keywords'] = "foo"
    result = vm(data)
    assert result == set(["keywords should be an array of strings"])
    
    data['keywords'] = [dict(hi="there")]
    result = vm(data)
    assert result == set(["keywords should be an array of strings"])
    
    data = dict(good_metadata)
    data['licenses'] = "GPL"
    result = vm(data)
    assert result == set(["licenses should be an array of objects http://semver.org"])
    
    data['licenses'] = ["GPL"]
    result = vm(data)
    assert result == set(["licenses should be an array of objects http://semver.org"])
    
    data = dict(good_metadata)
    data['depends'] = ["foo"]
    result = vm(data)
    assert result == set(["'depends' is not longer supported. use dependencies."])
    
    data = dict(good_metadata)
    data['dependencies'] = ['foo']
    result = vm(data)
    assert result == set(['dependencies should be a dictionary'])
    
    data['dependencies'] = dict(foo="bar")
    result = vm(data)
    assert result == set(["'bar' is not a valid version for dependency 'foo'"])
    
    data['dependencies'] = dict(foo="1.0.0")
    result = vm(data)
    assert result == set()
    
    data['depedencies'] = dict(foo=["1.0", "2.0"])
    result = vm(data)
    assert result == set()
    
    data['dependencies'] = dict(foo = ["invalid"])
    result = vm(data)
    assert result == set(["'invalid' is not a valid version for dependency 'foo'"])
    
    
def test_save_plugin_without_enough_metadata():
    try:
        plugins.save_to_gallery(macgyver, plugindir / "SingleFilePlugin1.js")
        assert False, "Expected to get an exception when saving a plugin without enough metadata"
    except plugins.PluginError:
        pass
    
def test_save_plugin_good():
    _init_data()
    gallery_root = config.c.gallery_root
    plugins.save_to_gallery(macgyver, plugindir / "plugin1")
    
    plugin1_dir = gallery_root / "plugin1"
    assert plugin1_dir.exists()
    version_dir = plugin1_dir / "0.9"
    assert version_dir.exists()
    assert version_dir.isdir()
    package_info = version_dir / "package.json"
    assert package_info.exists()
    
    s = config.c.session_factory()
    s.commit()
    s.clear()
    
    num_plugins = s.query(GalleryPlugin).count()
    assert num_plugins == 1
    plugin = s.query(GalleryPlugin).first()
    assert plugin.name == "plugin1"
    assert plugin.version == "0.9"
    assert plugin.packageInfo['description'] == "plugin the first."
    
def test_save_single_file_plugin_to_gallery():
    _init_data()
    gallery_root = config.c.gallery_root
    plugins.save_to_gallery(macgyver, plugindir / "SingleFilePlugin3.js")
    
    sfp3_dir = gallery_root / "singlefileplugin3"
    assert sfp3_dir.exists()
    version_file = sfp3_dir / "2.3.2.js"
    assert version_file.exists()
    assert not version_file.isdir()
    
def test_plugin_upload_from_the_web():
    _init_data()
    sfp = (path(__file__).dirname() / "plugindir").abspath() / "SingleFilePlugin3.js"
    sfp_content = sfp.text()
    response = app.put("/file/at/myplugins/singlefileplugin3.js", sfp_content)
    response = app.put("/file/at/BespinSettings/pluginInfo.json", """{
"plugins": ["myplugins/singlefileplugin3.js"],
"pluginOrdering": ["singlefileplugin3"]
}""")
    response = app.post("/plugin/upload/singlefileplugin3")
    assert response.body == "OK"
    
    s = config.c.session_factory()
    num_plugins = s.query(GalleryPlugin).count()
    assert num_plugins == 1
    plugin = s.query(GalleryPlugin).first()
    assert plugin.name == "singlefileplugin3"
    
    response = app.post("/plugin/upload/singlefileplugin3", status=400)
    print response.body
    assert response.body == "singlefileplugin3 version 2.3.2 already exists"
    
def test_plugin_upload_wont_replace_builtin_plugin():
    _init_data()
    
    response = app.post("/plugin/upload/Editor", status=400)
    print response.body
    assert response.body == "Cannot find plugin 'Editor' among user editable plugins"
    
def test_plugin_upload_wont_work_for_someone_elses_plugin():
    _init_data()
    
    sfp = (path(__file__).dirname() / "plugindir").abspath() / "SingleFilePlugin3.js"
    sfp_content = sfp.text()
    response = app.put("/file/at/myplugins/singlefileplugin3.js", sfp_content)
    response = app.put("/file/at/BespinSettings/pluginInfo.json", """{
"plugins": ["myplugins/singlefileplugin3.js"],
"pluginOrdering": ["singlefileplugin3"]
}""")
    response = app.post("/plugin/upload/singlefileplugin3")
    assert response.body == "OK"
    
    response = app_murdoc.put("/file/at/myplugins/singlefileplugin3.js", sfp_content)
    response = app_murdoc.put("/file/at/BespinSettings/pluginInfo.json", """{
"plugins": ["myplugins/singlefileplugin3.js"],
"pluginOrdering": ["singlefileplugin3"]
}""")
    response = app_murdoc.post("/plugin/upload/singlefileplugin3", status=401)
    print response.body
    assert response.body == "Plugin 'singlefileplugin3' is owned by another user"
    