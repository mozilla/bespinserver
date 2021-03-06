# -*- coding: utf8 -*-

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
from datetime import datetime, timedelta
from urllib import urlencode

from __init__ import BespinTestApp
import simplejson
from path import path

from sqlalchemy import and_

from bespin import config, controllers, filesystem

from bespin.filesystem import File, get_project, ProjectView
from bespin.filesystem import FSException, FileNotFound, OverQuota, FileConflict, BadValue
from bespin.database import User, Base, _get_session, EventLog

tarfilename = os.path.join(os.path.dirname(__file__), "ut.tgz")
zipfilename = os.path.join(os.path.dirname(__file__), "ut.zip")
otherfilename = os.path.join(os.path.dirname(__file__), "other_import.tgz")
with_tabs = os.path.join(os.path.dirname(__file__), "ProjectWithTabs.tgz")

app = None
macgyver = None
someone_else = None
murdoc = None

def setup_module(module):
    global app
    config.set_profile('test')
    app = controllers.make_app()
    app = BespinTestApp(app)
    
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
    
    someone_else = User.create_user("SomeoneElse", "", "someone@else.com")
    murdoc = User.create_user("Murdoc", "", "murdoc@badpeople.bad")
    
    otherproject = get_project(someone_else, someone_else,
                                            "otherproject", create=True)
    otherproject.save_file('foo', 'Just a file to reserve a project')
    
    app.post("/register/new/MacGyver", 
        dict(password="richarddean", email="rich@sg1.com"))
        
    macgyver = User.find_user("MacGyver")

def test_basic_file_creation():
    _init_data()
    starting_point = macgyver.amount_used
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("reqs", "Chewing gum wrapper")
    
    file_obj = File(bigmac, "reqs")
    data = str(file_obj.data)
    assert data == 'Chewing gum wrapper'
    ending_point = macgyver.amount_used
    difference = ending_point - starting_point
    assert difference == 19
    
    result = bigmac.search_files("eq")
    assert result == ['reqs']
    
    now = datetime.now()
    assert now - file_obj.created < timedelta(seconds=2)
    assert now - file_obj.modified < timedelta(seconds=2)
    
    bigmac = get_project(macgyver, macgyver, "bigmac")
    files = bigmac.list_files("")
    assert len(files) == 1
    assert files[0].short_name == 'reqs'
    proj_names = set([proj.name for proj in macgyver.projects])
    assert proj_names == set(['bigmac', "SampleProject", 
                              "BespinSettings"])

    # let's update the contents
    bigmac.save_file("reqs", "New content")
    file_obj = File(bigmac, "reqs")

    assert file_obj.data == 'New content'

def test_changing_file_contents_changes_amount_used():
    _init_data()
    starting_point = macgyver.amount_used
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo", "step 1")
    assert macgyver.amount_used == starting_point + 6
    bigmac.save_file("foo", "step two")
    assert macgyver.amount_used == starting_point + 8
    
def test_cannot_save_beyond_quota():
    _init_data()
    old_units = filesystem.QUOTA_UNITS
    filesystem.QUOTA_UNITS = 10
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    try:
        bigmac.save_file("foo", "x" * 11)
        assert False, "Expected an OverQuota exception"
    except OverQuota:
        pass
    finally:
        filesystem.QUOTA_UNITS = old_units
        
def test_amount_used_can_be_recomputed():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("secrets", "The password is pa55w0rd!")
    starting_point = macgyver.amount_used
    # open the file, to cause a status file to be created
    bigmac.get_file("secrets")
    macgyver.amount_used = 0
    macgyver.recompute_files()
    assert macgyver.amount_used == starting_point
    
def test_retrieve_file_obj():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("reqs", "tenletters")
    try:
        bigmac.get_file_object("foo/bar")
        assert False, "expected file not found for missing file"
    except FileNotFound:
        pass
        
    file_obj = bigmac.get_file_object("reqs")
    assert file_obj.saved_size == 10
        

def test_error_if_you_try_to_replace_dir_with_file():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo/bar/baz", "biz")
    try:
        bigmac.save_file("foo/bar", "NOT GONNA DO IT!")
        assert False, "Expected a FileConflict exception"
    except FileConflict:
        pass
    
def test_get_file_raises_exception_if_its_a_directory():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo/bar/baz", "biz")
    try:
        contents = bigmac.get_file("foo/bar/")
        assert False, "Expected exception for directory"
    except FSException:
        pass

def test_get_file_raises_not_found_exception():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo/bar/baz", "biz")
    try:
        contents = bigmac.get_file("NOTFOUND")
        assert False, "Expected exception for not found"
    except FileNotFound:
        pass

def test_directory_shortname_computed_to_have_last_dir():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo/bar/baz", "biz")
    res = bigmac.list_files("foo/")
    print res
    assert len(res) == 1
    d = res[0]
    shortname = d.short_name
    assert shortname == "bar/"

def test_can_delete_empty_directory():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.create_directory("foo/bar/")
    bigmac.delete("foo/bar/")
    location = bigmac.location / "foo/bar"
    assert not location.exists()

def test_delete_raises_file_not_found():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    try:
        bigmac.delete("DOESNT MATTER")
        assert False, "Expected not found for missing project"
    except FileNotFound:
        pass
    bigmac.save_file("foo/bar/baz", "biz")
    try:
        bigmac.delete("STILL DOESNT MATTER")
        assert False, "Expected not found for missing file"
    except FileNotFound:
        pass
    flist = bigmac.list_files()
    assert flist[0].name == "foo/"
    bigmac.delete("foo/bar/")
    
def test_successful_deletion():
    _init_data()
    starting_used = macgyver.amount_used
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo/bar/baz", "biz")
    
    files = bigmac.search_files("baz")
    assert files == ["foo/bar/baz"]
    
    bigmac.delete("foo/bar/baz")
    
    files = bigmac.search_files("baz")
    assert files == []
    
    assert macgyver.amount_used == starting_used
    try:
        bigmac.get_file("foo/bar/baz")
        assert False, "Expected FileNotFound because the file is gone"
    except FileNotFound:
        pass
    files = bigmac.list_files("foo/bar/")
    assert not files
    
def test_top_level_deletion():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo", "data")
    bigmac.delete("foo")
    flist = bigmac.list_files()
    assert flist == []
    
def test_directory_deletion():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("whiz/bang", "stillmore")
    starting_used = macgyver.amount_used
    bigmac.save_file("foo/bar", "data")
    bigmac.save_file("foo/blorg", "moredata")
    
    files = bigmac.search_files("blorg")
    assert files == ['foo/blorg']
    
    bigmac.delete("foo/")
    
    files = bigmac.search_files("blorg")
    assert files == []
    
    flist = bigmac.list_files()
    assert len(flist) == 1
    assert flist[0].name == 'whiz/'
    file_loc = bigmac.location / "foo/bar"
    assert not file_loc.exists()
    assert macgyver.amount_used == starting_used
    
    bigmac.save_file("newfoo/bar.txt", "just text")
    try:
        bigmac.delete("newfoo")
        assert False, "Expected an exception when deleting a directory without the trailing slash"
    except FSException, e:
        pass
    
def test_list_top_level():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("readme.txt", "Hi there!")
    result = bigmac.list_files()
    result_names = [file.name for file in result]
    assert result_names == ["readme.txt"]
    result = macgyver.projects
    result_names = [proj.name for proj in result]
    assert result_names == ["BespinSettings",
                            "SampleProject", "bigmac"]
    
    
def test_filesystem_can_be_arranged_in_levels():
    config.c.fslevels = 0
    _init_data()
    
    assert macgyver.file_location == macgyver.uuid
    
    config.c.fslevels = 1
    _init_data()
    fsroot = config.c.fsroot
    dirs = [d.basename() for d in fsroot.dirs()]
    # the first character should be peeled off as the top directory name
    for d in dirs:
        assert len(d) == 1

    uuid = macgyver.uuid
    assert macgyver.file_location == "%s/%s" % (uuid[0], uuid)
    
    config.c.fslevels = 2
    _init_data()
    uuid = macgyver.uuid
    assert macgyver.file_location == "%s/%s/%s" % (uuid[0], uuid[1], uuid)

def test_bad_project_names():
    _init_data()
    try:
        badone = get_project(macgyver, macgyver, "..", create=True)
        assert False, "Expected BadValue exception for bad name"
    except BadValue:
        pass
    try:
        badone = get_project(macgyver, macgyver, "foo/bar", create=True)
        assert False, "Expected BadValue exception for bad name"
    except BadValue:
        pass

def test_bad_files_and_directories():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    try:
        bigmac.save_file("../foo/bar", "hi")
        assert False, "Expected BadValue exception for bad name"
    except BadValue:
        pass
    
    bigmac.save_file("/tmp/foo", "hi")
    foopath = path("/tmp/foo")
    assert not foopath.exists()
    location = bigmac.location
    assert (location / "tmp" / "foo").exists()

def test_bad_directory_names():
    _init_data()
    p = path("/tmp/onlydirs/")
    assert not p.exists()
    p.makedirs()
    try:
        (p / "dir2").mkdir()
        (p / "dir3").mkdir()
        bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
        try:
            files = bigmac.list_files(p)
            assert False, "Expected exception for absolute dir"
        except BadValue:
            pass
        except FileNotFound:
            pass
    finally:
        p.rmtree()

def test_delete_directories_outside_of_tree():
    _init_data()
    p = path("/tmp/onlydirs/")
    assert not p.exists()
    p.makedirs()
    try:
        (p / "dir2").mkdir()
        (p / "dir3").mkdir()
        bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
        bigmac.save_file("tmp/onlydirs/newfile", "yo")
        files = bigmac.delete(p)
        assert p.exists()
    finally:
        if p.exists():
            p.rmtree()
    
def _setup_search_data():
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    for name in [
        "foo_bar",
        "whiz_bang",
        "ding_dong",
        "foo_some_other",
        "some_deeply_nested_file_here",
        "whiz_cheez",
        "bespin_rocks",
        "many_files",
        "cool+one",
        "some_1"
    ]:
        bigmac.save_file(name, "hi")
    return bigmac
    
def test_file_search():
    _init_data()
    bigmac = _setup_search_data()
    _run_search_tests(bigmac.search_files)
    
def _run_search_tests(search_func):
    result = search_func("")
    assert result == [
        "bespin_rocks",
        "cool+one",
        "ding_dong",
        "foo_bar",
        "foo_some_other",
        "many_files",
        "some_1",
        "some_deeply_nested_file_here",
        "whiz_bang",
        "whiz_cheez"
    ]
    
    result = search_func("o")
    assert result == [
        "bespin_rocks",
        "cool+one",
        "ding_dong",
        "foo_bar",
        "foo_some_other",
        "some_1",
        "some_deeply_nested_file_here"
    ]
    
    result = search_func("o", 2)
    assert result == [
        "bespin_rocks",
        "cool+one"
    ]
    
    result = search_func("os")
    assert result == [
        "bespin_rocks",
        "foo_some_other",
        "some_deeply_nested_file_here"
    ]
    
    result = search_func("me")
    assert result == [
        "foo_some_other",
        "some_1",
        "some_deeply_nested_file_here",
        "many_files"
    ]
    
    result = search_func("+")
    assert result == [
        "cool+one"
    ]
    
    result = search_func("ME")
    assert result == [
        "foo_some_other",
        "some_1",
        "some_deeply_nested_file_here",
        "many_files"
    ]
    
    result = search_func("so")
    assert result == [
        "foo_some_other",
        "some_1",
        "some_deeply_nested_file_here",
        "bespin_rocks"
    ]
    result = search_func("som")
    print result
    assert result == [
        "some_1",
        "foo_some_other",
        "some_deeply_nested_file_here"
    ]
    
    result = search_func(u'ø')
    assert result == []

def test_project_rename_should_be_secure():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    p = path('/tmp/foo')
    try:
        try:
            bigmac.rename("/tmp/foo")
            assert not p.exists()
        except BadValue:
            pass
    finally:
        if p.exists():
            p.rmdir()

# -------
# Web tests
# -------
    
def test_good_file_operations_from_web():
    _init_data()
    app.put("/file/at/bigmac/reqs", "Chewing gum wrapper")
    bigmac = get_project(macgyver, macgyver, "bigmac")
    fileobj = File(bigmac, "reqs")
    contents = str(fileobj.data)
    assert contents == "Chewing gum wrapper"
    
    s = _get_session()
    sel = EventLog.select().where(and_(EventLog.c.kind=='filesave', 
        EventLog.c.username=='MacGyver'))
    result = s.connection().execute(sel).fetchall()
    assert len(result) == 1
    
    resp = app.get("/file/at/bigmac/reqs")
    assert resp.body == "Chewing gum wrapper"
    
    resp = app.get("/file/at/bigmac/reqs?mode=r")
    assert resp.body == "Chewing gum wrapper"
    
    resp = app.get("/file/list/bigmac/")
    data = simplejson.loads(resp.body)
    print data
    
    resp = app.get("/file/list/")
    data = simplejson.loads(resp.body)
    assert data == [{'name' : 'BespinSettings/'},
                    {'name' : 'SampleProject/'}, 
                    {'name' : 'bigmac/'}]
    
    resp = app.get("/file/list/SampleProject/")
    data = simplejson.loads(resp.body)
    assert data[1]['name'] == 'index.html'
    
    resp = app.get("/file/list/bigmac/")
    assert resp.content_type == "application/json"
    data = simplejson.loads(resp.body)
    assert len(data) == 1
    data = data[0]
    assert data['name'] == 'reqs'
    assert data['size'] == 19
    assert data['created'].startswith("20")
    assert 'T' in data['created']
    assert data['modified'].startswith("20")
    assert 'T' in data['modified']
    
    app.delete("/file/at/bigmac/reqs")
    resp = app.get("/file/list/bigmac/")
    data = simplejson.loads(resp.body)
    assert data == []
    
    
def test_error_conditions_from_web():
    _init_data()
    app.get("/file/at/bigmac/UNKNOWN", status=404)
    app.put("/file/at/bigmac/bar/baz", "A file in bar")
    app.put("/file/at/bigmac/bar", "A file to replace bar", status=409)
    app.get("/file/at/bigmac/bar/baz")
    app.get("/file/at/bigmac", status=400)
    app.get("/file/at/bigmac/", status=400)
    app.get("/file/at/", status=400)

def test_get_file_stats_from_web():
    _init_data()
    app.put("/file/at/bigmac/reqs", "Chewing gum wrapper")
    resp = app.get("/file/stats/bigmac/reqs")
    assert resp.content_type == "application/json"
    data = simplejson.loads(resp.body)
    assert data['size'] == 19
    
def test_preview_mode():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("README.txt", "This is the readme file.")
    bigmac.save_file("foo.flibber", "Can't guess what this is!")
    
    resp = app.get("/preview/at/bigmac/", status=400)
    resp = app.get("/preview/at/bigmac/README.txt")
    assert resp.body == "This is the readme file."
    assert resp.content_type == "text/plain"
    
    resp = app.get("/preview/at/bigmac/foo.flibber")
    assert resp.content_type == "application/octet-stream"
    
    bigmac.save_file("index.html",
        "<html><body>Simple HTML file</body></html>")

    resp = app.get("/preview/at/bigmac/index.html")
    assert resp.body == "<html><body>Simple HTML file</body></html>"
    assert resp.content_type == "text/html"
    
def test_quota_limits_on_the_web():
    _init_data()
    old_units = filesystem.QUOTA_UNITS
    filesystem.QUOTA_UNITS = 10
    try:
        resp = app.put("/file/at/bigmac/foo", "x" * 11, status=400)
        assert resp.body == "Over quota"
    finally:
        filesystem.QUOTA_UNITS = old_units

def test_search_from_the_web():
    _init_data()
    bigmac = _setup_search_data()
    resp = app.get("/file/search/bigmac")
    assert resp.content_type == "application/json"
    def run_search(q, limit=20):
        resp = app.get("/file/search/bigmac?%s" 
            % urlencode([('q', q.encode('utf-8')), ('limit', limit)]))
        assert resp.content_type == "application/json"
        return simplejson.loads(resp.body)
    _run_search_tests(run_search)
    
    # illegal limits are turned into the default
    resp = app.get("/file/search/bigmac?limit=foo")
    
def test_list_all_files():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    bigmac.save_file("foo/bar/baz.txt", "Text file 1\n")
    bigmac.save_file("README.txt", "Another file\n")
    bigmac.save_file("bespin/noodle.py", "# A python file\n")
    resp = app.get("/file/list_all/bigmac/")
    assert resp.content_type == "application/json"
    data = simplejson.loads(resp.body)
    assert len(data) == 3
    
def test_handling_of_symlinks():
    _init_data()
    bigmac = get_project(macgyver, macgyver, "bigmac", create=True)
    linksource = bigmac.location / "thefile"
    linksource.write_bytes("Hi")
    linkdest = bigmac.location / "thelink"
    linksource.symlink(linkdest)
    assert linkdest.exists()
    assert linkdest.islink()
    resp = app.get("/file/at/bigmac/thelink", status=400)
    resp = app.put("/file/at/bigmac/thelink", "new data", status=400)
    assert linksource.bytes() == "Hi"
    
    thisdir = path(__file__).dirname()
    linkdest = bigmac.location / "dirlink"
    thisdir.symlink(linkdest)
    assert linkdest.exists()
    assert linkdest.isdir()
    resp = app.get("/file/list/bigmac/dirlink/", status=400)
    