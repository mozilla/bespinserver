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
import urllib2
import httplib2
from urlparse import urlparse
import logging
from datetime import date
import socket
import urllib
from hashlib import sha256
import re

from urlrelay import URLRelay, register
from paste.auth import auth_tkt
from paste.proxy import Proxy
import simplejson
import tempfile
import static
from webob import Request, Response

from bespin.config import c
from bespin.framework import expose, BadRequest
from bespin import vcs, deploy
from bespin.database import User, get_project
from bespin.filesystem import NotAuthorized, OverQuota, File, FileNotFound
from bespin.utils import send_email_template
from bespin import filesystem, queue, plugins

log = logging.getLogger("bespin.controllers")

@expose(r'^/register/new/(?P<username>.*)$', 'POST', auth=False)
def new_user(request, response):
    try:
        username = request.kwargs['username']
        email = request.POST['email']
        password = request.POST['password']
    except KeyError:
        raise BadRequest("username, email and password are required.")
    user = User.create_user(username, password, email)

    settings_project = get_project(user, user, "BespinSettings", create=True)
    settings_project.install_template('usertemplate')
    response.content_type = "application/json"
    response.body = "{}"
    request.environ['paste.auth_tkt.set_user'](username)
    return response()

def _get_capabilities():
    return dict(
        capabilities = list(c.capabilities),
        javaScriptPlugins = list(c.javascript_plugins),
        dojoModulePath = c.dojo_module_path
    )

@expose('^/capabilities/$', 'GET')
def capabilities(request, response):
    response.content_type = "application/json"
    result = _get_capabilities()
    response.body = simplejson.dumps(result)
    return response()
    
@expose(r'^/register/userinfo/$', 'GET')
def get_registered(request, response):
    response.content_type = "application/json"
    if request.user:
        quota, amount_used = request.user.quota_info()
    else:
        quota = None
        amount_used = None
    response.body=simplejson.dumps(
        dict(username=request.username,
        quota=quota, amountUsed=amount_used,
        serverCapabilities=_get_capabilities())
    )
    return response()

@expose(r'^/register/login/(?P<login_username>.+)', 'POST', auth=False)
def login(request, response):
    username = request.kwargs['login_username']
    password = request.POST.get('password')
    fli = c.login_tracker.can_log_in(username)
    if not fli.can_log_in:
        response.status = "401 Not Authorized"
        response.body = "Locked out due to failed login attempts."
        return response()
        
    user = User.find_user(username, password)
    if not user:
        c.login_tracker.login_failed(fli)
        response.status = "401 Not Authorized"
        response.body = "Invalid login"
        return response()
    
    c.login_tracker.login_successful(fli)
    request.environ['paste.auth_tkt.set_user'](username)
    
    response.content_type = "application/json"
    response.body="{}"
    return response()

@expose(r'^/register/logout/$')
def logout(request, response):
    request.environ['paste.auth_tkt.logout_user']()
    response.status = "200 OK"
    response.body = "Logged out"
    return response()
    
def _get_password_verify_code(user):
    h = sha256()
    h.update(c.secret)
    h.update(user.username)
    h.update(user.password)
    return h.hexdigest()

@expose(r'^/register/lost/$', 'POST', auth=False)
def lost(request, response):
    """Generates lost password email messages"""
    email = request.POST.get('email')
    username = request.POST.get('username')
    if username:
        user = User.find_user(username)
        if not user:
            raise BadRequest("Unknown user: " + username)
            
        verify_code = _get_password_verify_code(user)
        change_url = c.base_url + "?pwchange=%s;%s" % (username, verify_code)
        context = dict(username=username, base_url=c.base_url,
                        change_url=change_url)
        
        send_email_template(user.email, "Requested password change for " + c.base_url,
                            "lost_password.txt", context)
        
    elif email:
        users = User.find_by_email(email)
        context = dict(email=email,
            usernames=[dict(username=user.username) for user in users],
            base_url=c.base_url)
        send_email_template(email, "Your username for " + c.base_url,
                            "lost_username.txt", context)
    else:
        raise BadRequest("Username or email is required.")
        
    return response()

@expose(r'^/register/password/(?P<username>.+)$', 'POST', auth=False)
def password_change(request, response):
    """Changes a user's password."""
    username = request.kwargs.get('username')
    user = User.find_user(username)
    if not user:
        raise BadRequest("Unknown user: " + username)
    verify_code = _get_password_verify_code(user)
    code = request.POST.get('code')
    if verify_code != code:
        raise BadRequest("Invalid verification code for password change.")
    user.password = User.generate_password(request.POST['newPassword'])
    return response()

@expose(r'^/settings/$', 'POST')
def save_settings(request, response):
    """Saves one or more settings for the currently logged in user."""
    user = request.user
    user.settings.update(request.POST)
    # make it so that the user obj appears dirty to SQLAlchemy
    user.settings = user.settings
    return response()

@expose(r'^/settings/(?P<setting_name>.*)$', 'GET')
def get_settings(request, response):
    """Retrieves one setting or all (depending on URL)."""
    kwargs = request.kwargs
    user = request.user
    response.content_type='application/json'
    setting_name = kwargs['setting_name']
    if setting_name:
        try:
            response.body=simplejson.dumps(user.settings[setting_name])
        except KeyError:
            response.status = '404 Not Found'
            response.body = '%s not found' % setting_name
            response.content_type="text/plain"
    else:
        response.body=simplejson.dumps(user.settings)
    return response()

@expose(r'^/settings/(?P<setting_name>.+)$', 'DELETE')
def delete_setting(request, response):
    user = request.user
    kwargs = request.kwargs
    setting_name = kwargs['setting_name']
    try:
        del user.settings[setting_name]
        # get the user to appear dirty
        user.settings = user.settings
    except KeyError:
        response.status = "404 Not Found"
    return response()

def _split_path(request):
    path = request.kwargs['path']
    result = path.split('/', 1)
    if len(result) < 2:
        raise BadRequest("Project and path are both required.")
    parts = result[0].partition('+')
    if parts[1] == '':
        result.insert(0, request.user)
    else:
        result.insert(0, User.find_user(parts[0]))
        result[1] = parts[2]
    return result

@expose(r'^/file/listopen/$', 'GET')
def listopen(request, response):
    user = request.user
    result = user.files
    response.content_type = "application/json"
    response.body = simplejson.dumps(result)
    return response()

@expose(r'^/file/at/(?P<path>.*)$', 'PUT')
def putfile(request, response):
    user = request.user

    owner, project, path = _split_path(request)
    project = get_project(user, owner, project, create=True)

    if path.endswith('/'):
        if request.body != None and request.body != '':
            raise BadRequest("Path ended in '/' indicating directory, but request contains ")
        project.create_directory(path)
    elif path:
        project.save_file(path, request.body)
    return response()

@expose(r'^/file/at/(?P<path>.*)$', 'GET')
def getfile(request, response):
    user = request.user

    owner, project, path = _split_path(request)
    project = get_project(user, owner, project)

    mode = request.GET.get('mode', 'rw')
    contents = project.get_file(path, mode)
    response.body = contents
    response.content_type = "zombie/brains"
    return response()

@expose(r'^/file/close/(?P<path>.*)$', 'POST')
def postfile(request, response):
    user = request.user

    owner, project, path = _split_path(request)
    project = get_project(user, owner, project)

    project.close(path)
    return response()

@expose(r'^/file/at/(?P<path>.*)$', 'DELETE')
def deletefile(request, response):
    user = request.user

    owner, project, path = _split_path(request)
    project = get_project(user, owner, project)

    project.delete(path)
    return response()

@expose(r'^/file/list/(?P<path>.*)$', 'GET')
def listfiles(request, response):
    user = request.user
    path = request.kwargs['path']
    result = []

    if not path:
        projects = request.user.get_all_projects(True)
        for project in projects:
            if project.owner == user:
                result.append({ 'name':project.short_name })
            else:
                result.append({ 'name':project.owner.username + "+" + project.short_name })
    else:
        try:
            owner, project, path = _split_path(request)
        except BadRequest:
            project = path
            path = ''

        if project:
            project = get_project(user, owner, project)

        files = project.list_files(path)

        for item in files:
            reply = { 'name':item.short_name }
            _populate_stats(item, reply)
            result.append(reply)

    return _respond_json(response, result)

@expose(r'^/project/template/(?P<project_name>.*)/$', 'POST')
def install_template(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    data = simplejson.loads(request.body)
    try:
        template_name = data['templateName']
    except KeyError:
        raise BadRequest("templateName not provided in request")
        
    project = get_project(user, user, project_name, create=True)
    project.install_template(template_name, data)
    
    response.content_type = "text/plain"
    response.body = ""
    return response()
    
@expose(r'^/project/rescan/(?P<project_name>.*$)', 'POST')
def rescan_project(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    project = get_project(user, user, project_name)
    job_body = dict(user=user.username, project=project_name)
    jobid = queue.enqueue("vcs", job_body, execute="bespin.filesystem:rescan_project",
                        error_handler="bespin.vcs:vcs_error",
                        use_db=True)
    response.content_type = "application/json"
    response.body = simplejson.dumps(dict(jobid=jobid, 
                    taskname="Rescan %s" % project_name))
    return response()
    
@expose(r'^/file/template/(?P<path>.*)', 'PUT')
def install_file_template(request, response):
    user = request.user
    owner, project, path = _split_path(request)
    
    project = get_project(user, user, project, create=True)
    options = simplejson.loads(request.body)
    project.install_template_file(path, options)
    
    response.body = ""
    response.content_type = "text/plain"
    return response()

@expose(r'^/file/list_all/(?P<project_name>.*)/$', 'GET')
def file_list_all(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    project = get_project(user, user, project_name)
    metadata = project.metadata

    files = metadata.get_file_list()
    metadata.close()
    
    return _respond_json(response, files)

@expose(r'^/file/search/(?P<project_name>.*)$', 'GET')
def file_search(request, response):
    user = request.user
    query = request.GET.get("q", "")
    query = query.decode("utf-8")
    include = request.GET.get("i", "")
    limit = request.GET.get("limit", 20)
    try:
        limit = int(limit)
    except ValueError:
        limit = 20
    project_name = request.kwargs['project_name']

    project = get_project(user, user, project_name)
    result = project.search_files(query, limit, include)
    return _respond_json(response, result)

def _populate_stats(item, result):
    if isinstance(item, File):
        result['size'] = item.saved_size
        result['created'] = item.created.strftime("%Y%m%dT%H%M%S")
        result['modified'] = item.modified.strftime("%Y%m%dT%H%M%S")
        result['openedBy'] = [username for username in item.users]
    
@expose(r'^/file/stats/(?P<path>.+)$', 'GET')
def filestats(request, response):
    user = request.user

    owner, project, path = _split_path(request)
    project = get_project(user, owner, project)

    file_obj = project.get_file_object(path)
    result = {}
    _populate_stats(file_obj, result)
    return _respond_json(response, result)

@expose(r'^/project/import/(?P<project_name>[^/]+)', "POST")
def import_project(request, response):
    project_name = request.kwargs['project_name']
    input_file = request.POST['filedata']
    filename = input_file.filename
    _perform_import(request.user, project_name, filename,
                    input_file.file)
    return response()
    
def _perform_import(user, project_name, filename, fileobj):
    project = get_project(user, user, project_name, clean=True)
    if filename.endswith(".tgz") or filename.endswith(".tar.gz"):
        func = project.import_tarball
    elif filename.endswith(".zip"):
        func = project.import_zipfile
    else:
        raise BadRequest(
            "Import only supports .tar.gz, .tgz and .zip at this time.")
    
    func(filename, fileobj)
    return

def validate_url(url):
    if not url.startswith("http://") and not url.startswith("https://"):
        raise BadRequest("Invalid url: " + url)
    return url
    
@expose(r'^/project/fromurl/(?P<project_name>[^/]+)', "POST")
def import_from_url(request, response):
    project_name = request.kwargs['project_name']
    
    url = validate_url(request.body)
    try:
        resp = httplib2.Http().request(url, method="HEAD")
    except httplib2.HttpLib2Error, e:
        raise BadRequest(str(e))
        
    # check the content length to see if the user has enough quota
    # available before we download the whole file
    content_length = resp[0].get("content-length")
    if content_length:
        content_length = int(content_length)
        if not request.user.check_save(content_length):
            raise OverQuota()
    
    try:
        datafile = urllib2.urlopen(url)
    except urllib2.URLError, e:
        raise BadRequest(str(e))
    tempdatafile = tempfile.NamedTemporaryFile()
    tempdatafile.write(datafile.read())
    datafile.close()
    tempdatafile.seek(0)
    url_parts = urlparse(url)
    filename = os.path.basename(url_parts[2])
    _perform_import(request.user, project_name, filename, tempdatafile)
    tempdatafile.close()
    return response()

@expose(r'^/project/export/(?P<project_name>.*(\.zip|\.tgz))')
def export_project(request, response):
    user = request.user
    
    project_name = request.kwargs['project_name']
    project_name, extension = os.path.splitext(project_name)

    project = get_project(user, user, project_name)
    
    if extension == ".zip":
        func = project.export_zipfile
        response.content_type = "application/zip"
    else:
        response.content_type = "application/x-tar-gz"
        func = project.export_tarball
    
    output = func()
    def filegen():
        data = output.read(8192)
        while data:
            yield data
            data = output.read(8192)
        raise StopIteration
    response.app_iter = filegen()
    return response()
    
@expose(r'^/preview/at/(?P<path>.+)$')
def preview_file(request, response):
    user = request.user
    
    owner, project, path = _split_path(request)
    if owner != user:
        raise BadRequest("Preview of shared projects is not currently supported for security reasons.")
    
    project = get_project(user, owner, project)
    
    file_obj = project.get_file_object(path)
    response.body = str(file_obj.data)
    response.content_type = file_obj.mimetype
    return response()
    
@expose(r'^/project/rename/(?P<project_name>.+)/$', 'POST')
def rename_project(request, response):
    user = request.user

    project_name = request.kwargs['project_name']
    project = get_project(user, user, project_name)
    project.rename(request.body)
    response.body = ""
    response.content_type = "text/plain"
    return response()

@expose(r'^/network/followers/', 'GET')
def follow(request, response):
    return _users_followed_response(request.user, response)

@expose(r'^/network/follow/', 'POST')
def follow(request, response):
    users = _lookup_usernames(simplejson.loads(request.body))
    for other_user in users:
        request.user.follow(other_user)
    return _users_followed_response(request.user, response)

@expose(r'^/network/unfollow/', 'POST')
def unfollow(request, response):
    users = _lookup_usernames(simplejson.loads(request.body))
    for other_user in users:
        request.user.unfollow(other_user)
    return _users_followed_response(request.user, response)

@expose(r'^/group/list/all', 'GET')
def group_list_all(request, response):
    groups = request.user.get_groups()
    groups = [ group.name for group in groups ]
    return _respond_json(response, groups)

@expose(r'^/group/list/(?P<group>[^/]+)/$', 'GET')
def group_list(request, response):
    group_name = request.kwargs['group']
    group = request.user.get_group(group_name, raise_on_not_found=True)
    members = group.get_members()
    members = [ member.user.username for member in members ]
    return _respond_json(response, members)

@expose(r'^/group/remove/all/(?P<group>[^/]+)/$', 'POST')
def group_remove_all(request, response):
    group_name = request.kwargs['group']
    group = request.user.get_group(group_name, raise_on_not_found=True)
    rows = 0
    rows += group.remove_all_members()
    rows += group.remove()
    return _respond_json(response, rows)

@expose(r'^/group/remove/(?P<group>[^/]+)/$', 'POST')
def group_remove(request, response):
    group_name = request.kwargs['group']
    group = request.user.get_group(group_name, raise_on_not_found=True)
    users = _lookup_usernames(simplejson.loads(request.body))
    rows = 0
    for other_user in users:
        rows += group.remove_member(other_user)
    members = group.get_members()
    if len(members) == 0:
        rows += group.group()
    return _respond_json(response, rows)

@expose(r'^/group/add/(?P<group>[^/]+)/$', 'POST')
def group_add(request, response):
    group_name = request.kwargs['group']
    group = request.user.get_group(group_name, create_on_not_found=True)
    users = _lookup_usernames(simplejson.loads(request.body))
    for other_user in users:
        group.add_member(other_user)
    return _respond_blank(response)

def _respond_blank(response):
    response.body = ""
    response.content_type = "text/plain"
    return response()

def _respond_json(response, data):
    response.body = simplejson.dumps(data)
    response.content_type = "application/json"
    return response()

def _lookup_usernames(usernames):
    def lookup_username(username):
        user = User.find_user(username)
        if user == None:
            raise BadRequest("Username not found: %s" % username)
        return user
    return map(lookup_username, usernames)

def _users_followed_response(user, response):
    list = user.users_i_follow()
    list = [connection.followed.username for connection in list]
    response.body = simplejson.dumps(list)
    response.content_type = "text/plain"
    return response()

@expose(r'^/share/list/all/$', 'GET')
def share_list_all(request, response):
    "List all project shares"
    data = request.user.get_sharing()
    return _respond_json(response, data)

@expose(r'^/share/list/(?P<project>[^/]+)/$', 'GET')
def share_list_project(request, response):
    "List sharing for a given project"
    project = get_project(request.user, request.user, request.kwargs['project'])
    data = request.user.get_sharing(project)
    return _respond_json(response, data)

@expose(r'^/share/list/(?P<project>[^/]+)/(?P<member>[^/]+)/$', 'GET')
def share_list_project_member(request, response):
    "List sharing for a given project and member"
    project = get_project(request.user, request.user, request.kwargs['project'])
    member = request.user.find_member(request.kwargs['member'])
    data = request.user.get_sharing(project, member)
    return _respond_json(response, data)

@expose(r'^/share/remove/(?P<project>[^/]+)/all/$', 'POST')
def share_remove_all(request, response):
    "Remove all sharing from a project"
    project = get_project(request.user, request.user, request.kwargs['project'])
    data = request.user.remove_sharing(project)
    return _respond_json(response, data)

@expose(r'^/share/remove/(?P<project>[^/]+)/(?P<member>[^/]+)/$', 'POST')
def share_remove(request, response):
    "Remove project sharing from a given member"
    project = get_project(request.user, request.user, request.kwargs['project'])
    member = request.user.find_member(request.kwargs['member'])
    data = request.user.remove_sharing(project, member)
    return _respond_json(response, data)

@expose(r'^/share/add/(?P<project>[^/]+)/(?P<member>[^/]+)/$', 'POST')
def share_add(request, response):
    "Add a member to the sharing list for a project"
    project = get_project(request.user, request.user, request.kwargs['project'])
    member = request.user.find_member(request.kwargs['member'])
    options = simplejson.loads(request.body)
    request.user.add_sharing(project, member, options)
    return _respond_blank(response)

@expose(r'^/viewme/list/all/$', 'GET')
def viewme_list_all(request, response):
    "List all the members with view settings on me"
    data = request.user.get_viewme()
    return _respond_json(response, data)

@expose(r'^/viewme/list/(?P<member>[^/]+)/$', 'GET')
def viewme_list(request, response):
    "List the view settings for a given member"
    member = request.user.find_member(request.kwargs['member'])
    data = request.user.get_viewme(member)
    return _respond_json(response, data)

@expose(r'^/viewme/set/(?P<member>[^/]+)/(?P<value>[^/]+)/$', 'POST')
def viewme_set(request, response):
    "Alter the view setting for a given member"
    member = request.user.find_member(request.kwargs['member'])
    value = request.kwargs['value']
    data = request.user.set_viewme(member, value)
    return _respond_json(response, data)


from bespin.mobwrite.mobwrite_daemon import DaemonMobWrite
from bespin.mobwrite.mobwrite_daemon import maybe_cleanup

class MobwriteInProcess(DaemonMobWrite):
    "Talk to an in-process mobwrite"

    def processRequest(self, question):
        "Since we are a MobWriteWorker we just call directly into mobwrite code"
        answer = self.handleRequest(question)
        maybe_cleanup()
        return answer

class MobwriteTelnetProxy():
    "Talk to mobwrite using port 3017"

    def processRequest(self, question):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((c.mobwrite_server_address, c.mobwrite_server_port))
        s.send(question)
        answer = ''
        while True:
            line = s.recv(1024)
            if not line:
                break
            answer += line
        s.close()
        return answer

class MobwriteHttpProxy():
    "Talk to mobwrite over HTTP"

    def processRequest(self, question):
        url = "http://%s:%s/" % (c.mobwrite_server_address,
                                 c.mobwrite_server_port)
        try:
            datafile = urllib2.urlopen(url, question)
        except urllib2.URLError, e:
            raise BadRequest(str(e))

        answer = datafile.read()
        datafile.close()
        return answer

@expose(r'^/mobwrite/$', 'POST')
def mobwrite(request, response):
    """Handle a request for mobwrite synchronization.

    We talk to mobwrite either in-process for development or using a socket
    which would be more common in live."""
    c.stats.incr("mobwrite_DATE")
    question = urllib.unquote(request.body)
    # Hmmm do we need to handle 'p' requests? q.py does.
    mode = None
    if question.find("p=") == 0:
        mode = "script"
    elif question.find("q=") == 0:
        mode = "text"
    else:
        raise BadRequest("Missing q= or p=")
    question = question[2:]
    question = "H:" + str(request.user.username) + "\n" + question

    # Java: Class.forName(...) There *has* to be a better way in python?
    if c.mobwrite_implementation == "MobwriteInProcess":
        worker = MobwriteInProcess()
    if c.mobwrite_implementation == "MobwriteTelnetProxy":
        worker = MobwriteTelnetProxy()
    if c.mobwrite_implementation == "MobwriteHttpProxy":
        worker = MobwriteHttpProxy()

    #log.debug("\n\nQUESTION:\n" + question);
    answer = worker.processRequest(question)
    #log.debug("\nANSWER:\n" + answer + "\n");

    if mode == "text":
        response.body = answer + "\n\n"
        response.content_type = "text/plain"
    else:
        answer = answer.replace("\\", "\\\\").replace("\"", "\\\"")
        answer = answer.replace("\n", "\\n").replace("\r", "\\r")
        answer = "mobwrite.callback(\"%s\");" % answer
        response.body = answer
        response.content_type = "application/javascript"
    return response()


test_users = [ "ev", "tom", "mattb", "zuck" ]

@expose(r'^/test/setup/$', 'POST')
def test_setup(request, response):
    for name in test_users:
        user = User.find_user(name)
        if (user == None):
            user = User.create_user(name, name, name)
    response.body = ""
    response.content_type = "text/plain"
    return response()

@expose(r'^/test/cleanup/$', 'POST')
def test_cleanup(request, response):
    response.body = ""
    response.content_type = "text/plain"
    return response()
    
@expose(r'^/vcs/clone/$', 'POST')
def vcs_clone(request, response):
    user = request.user
    source = request.POST.get("source")
    taskname = "Clone/checkout"
    if source:
         taskname += " from %s" % (source)
    jobid = vcs.clone(user, **dict(request.POST))
    response.content_type = "application/json"
    response.body = simplejson.dumps(dict(jobid=jobid, taskname=taskname))
    return response()
    
@expose(r'^/vcs/command/(?P<project_name>.*)/$', 'POST')
def vcs_command(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    request_info = simplejson.loads(request.body)
    args = request_info['command']
    log.debug("VCS command: %s", args)
    kcpass = request_info.get('kcpass')
    
    try:
        taskname = "vcs %s command" % (args[0])
    except IndexError:
        taskname = "vcs command"
    
    # special support for clone/checkout
    if vcs.is_new_project_command(args):
        raise BadRequest("Use /vcs/clone/ to create a new project")
    else:
        project = get_project(user, user, project_name)
        jobid = vcs.run_command(user, project, args, kcpass)
    
    response.content_type = "application/json"
    response.body = simplejson.dumps(dict(jobid=jobid, taskname=taskname))
    return response()

@expose(r'^/vcs/remoteauth/(?P<project_name>.*)/$', 'GET')
def vcs_remoteauth(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    
    project = get_project(user, user, project_name)
    metadata = project.metadata
    value = metadata.get(vcs.AUTH_PROPERTY, "")
    
    response.content_type = "text/plain"
    response.body = value.encode("utf8")
    return response()

@expose(r'^/vcs/setauth/(?P<project_name>.*)/$', 'POST')
def keychain_setauth(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    project = get_project(user, user, project_name)
    
    try:
        kcpass = request.POST['kcpass']
        atype = request.POST['type']
        remote_auth = request.POST['remoteauth']
    except KeyError:
        raise BadRequest("Request must include kcpass, type and remoteauth.")
        
    if remote_auth != vcs.AUTH_WRITE and remote_auth != vcs.AUTH_BOTH:
        raise BadRequest("Remote auth type must be %s or %s" % 
                        (vcs.AUTH_WRITE, vcs.AUTH_BOTH))
    keychain = vcs.KeyChain(user, kcpass)
    
    body = ""
    
    if atype == "password":
        try:
            username = request.POST['username']
            password = request.POST['password']
        except KeyError:
            raise BadRequest("Request must include username and password")
        
        keychain.set_credentials_for_project(project, remote_auth, username, 
                                             password)
    elif atype == "ssh":
        # set the project to use the SSH key and return the public key
        body = keychain.set_ssh_for_project(project, remote_auth)[0]
    else:
        raise BadRequest("auth type must be ssh or password")
        
    response.content_type = "application/json"
    response.body = body
    return response()
    
@expose("^/vcs/getkey/$", 'POST')
def get_ssh_key(request, response):
    user = request.user
    try:
        kcpass = request.POST['kcpass']
    except KeyError:
        kcpass = None
        
    if kcpass is None:
        pubkey = vcs.KeyChain.get_ssh_public_key(user)
    else:
        keychain = vcs.KeyChain(user, kcpass)
        pubkey = keychain.get_ssh_key()[0]
        
    response.content_type = "application/x-ssh-key"
    response.body = pubkey
    return response()

@expose("^/messages/$", 'POST')
def messages(request, response):
    c.stats.incr("messages_DATE")
    user = request.user
    body = u"[" + ",".join(user.pop_messages()) + "]"

    response.content_type = "application/json"
    response.body = body.encode("utf8")
    return response()

@expose('^/stats/$', 'GET')
def stats(request, response):
    username = request.username
    if username not in c.stats_users:
        raise NotAuthorized("Not allowed to access stats")
    today = date.today().strftime("%Y%m%d")
    keys = ["exceptions_" + today,
           'requests_' + today,
           'mobwrite_' + today,
           'messages_' + today,
           'users',
           'files',
           'projects',
           'vcs_' + today]
    more_keys = [k.replace("_DATE", "_" + today) for k in c.stats_display]
    keys.extend(more_keys)
    result = c.stats.multiget(keys)
    response.content_type = "application/json"
    response.body = simplejson.dumps(result)
    return response()
    
@expose('^/project/deploy/(?P<project_name>[^/]+)/setup$', 'PUT')
def deploy_setup(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    project = get_project(user, user, project_name)
    
    data = simplejson.loads(request.body)
    deploy_options = dict(remote_host = data.get("remoteHost"),
        remote_directory = data.get("remoteDirectory"),
        type = data.get("connType"))
    
    try:
        pdo = deploy.ProjectDeploymentOptions(project, **deploy_options)
        pdo.save()
    except deploy.InvalidConfiguration, e:
        raise BadRequest(e.message)
    
    keychain = deploy.DeploymentKeyChain(user, data['kcpass'])
    if data['authType'] == "ssh":
        keychain.set_ssh_for_project(project, username=data['username'])
    else:
        keychain.set_credentials_for_project(project,
            username=data['username'],
            password=data['password'])
    
    project.metadata.close()
    
    response.content_type="application/json"
    response.body=""
    return response()

@expose('^/project/deploy/(?P<project_name>[^/]+)/setup$', 'POST')
def retrieve_deploy_setup(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    project = get_project(user, user, project_name)
    
    data = simplejson.loads(request.body)
    
    response.content_type="application/json"
    
    pdo = deploy.ProjectDeploymentOptions.get(project)
    if not pdo:
        response.body = simplejson.dumps(None)
        return response()
        
    kc = deploy.DeploymentKeyChain(user, data['kcpass'])
    cred = kc.get_credentials_for_project(project)
    
    result = dict(remoteHost=pdo.remote_host,
        remoteDirectory=pdo.remote_directory,
        connType=pdo.type, authType=cred['type'],
        username=cred['username'])
    
    result['password'] = cred['password'] \
        if cred['type'] == "password" else ""
        
    response.body = simplejson.dumps(result)
    return response()
    
@expose(r'^/project/deploy/(?P<project_name>[^/]+)/$', 'POST')
def run_deploy(request, response):
    user = request.user
    project_name = request.kwargs['project_name']
    data = simplejson.loads(request.body)
    kcpass = data['kcpass']
    
    options = dict()
    if "dryRun" in data:
        options['dry_run'] = data['dryRun']
    
    project = get_project(user, user, project_name)
    response.content_type = "application/json"
    try:
        jobid = deploy.run_deploy(user, project, kcpass, options)
    except deploy.NotConfigured, e:
        response.body = simplejson.dumps(dict(error=str(e),
            notConfigured=True))
        response.status = "400 Bad Request"
        return response()
    
    response.body = simplejson.dumps(dict(jobid=jobid, 
        taskname="deploy %s" % (project_name)))
    return response()
    
def _plugin_response(response, path=None, plugin_list=None):
    response.content_type = "application/json"
    
    
    if plugin_list is None:
        plugin_list = plugins.find_plugins(path)

    metadata = dict((plugin.name, plugin.metadata) 
        for plugin in plugin_list)
    
    response.body = simplejson.dumps(metadata)
    return response()

@expose(r'^/plugin/register/defaults$', 'GET', auth=False)
def register_plugins(request, response):
    return _plugin_response(response)

leading_slash = re.compile("^/")

def _get_user_plugin_path(request):
    user = request.user
    if not user:
        return []
        
    project = get_project(user, user, "BespinSettings")
    
    pluginInfo = None
    try:
        pluginInfo_content = project.get_file("pluginInfo.json")
        pluginInfo = simplejson.loads(pluginInfo_content)
    except FileNotFound:
        pass
    except ValueError:
        pass
    
    path = []
    if pluginInfo:
        root = user.get_location()
        root_len = len(root)
        pi_plugins = pluginInfo.get("plugins", None)
        # NOTE: it's important to trim leading slashes from these paths
        # because the user can edit the pluginInfo.json file directly.
        if pi_plugins:
            path.extend(dict(name="user", plugin = root / leading_slash.sub("", p), chop=root_len) for p in pi_plugins)
        pi_path = pluginInfo.get("path", None)
        if pi_path:
            path.extend(dict(name="user", path=root / leading_slash.sub("", p), chop=root_len) for p in pi_path)
        
    path.append(dict(name="user", path=project.location / "plugins", 
        chop=len(user.get_location())))
    return path
    
@expose(r'^/plugin/register/user$', 'GET', auth=True)
def register_user_plugins(request, response):
    path = _get_user_plugin_path(request)
    return _plugin_response(response, path)

@expose(r'^/plugin/register/tests$', 'GET', auth=False)
def register_test_plugins(request, response):
    if "test_plugin_path" not in c:
        raise FileNotFound("Test plugins are only in development environment")
    return _plugin_response(response, c.test_plugin_path)


@expose(r'^/plugin/script/(?P<plugin_location>[^/]+)/(?P<plugin_name>[^/]+)/(?P<path>.*)', 'GET', auth=False)
def load_script(request, response):
    response.content_type = "text/javascript"
    plugin_name = request.kwargs['plugin_name']
    plugin_location = request.kwargs['plugin_location']
    script_path = request.kwargs['path']
    if ".." in plugin_name or ".." in script_path or ".." in plugin_location:
        raise BadRequest("'..' not allowed in plugin or script names")
    
    path = None
    for path_entry in c.plugin_path:
        if path_entry['name'] == plugin_location:
            path = path_entry
    
    if path is None:
        raise FileNotFound("Plugin location %s unknown" % (plugin_location))
        
    plugin = plugins.lookup_plugin(plugin_name, [path])
    if not plugin:
        response.status = "404 Not Found"
        response.content_type = "text/plain"
        response.body = "Plugin " + plugin_name + " does not exist"
        return response()
    
    script_text = plugin.get_script_text(script_path)
    response.body = _wrap_script(plugin_name, script_path, script_text)
    return response()
    
@expose(r'^/plugin/file/(?P<plugin_location>[^/]+)/(?P<plugin_name>[^/]+)/(?P<path>.*)', 'GET', auth=False)
def load_file(request, response):
    plugin_name = request.kwargs['plugin_name']
    plugin_location = request.kwargs['plugin_location']
    script_path = request.kwargs['path']
    if ".." in plugin_name or ".." in script_path or ".." in plugin_location:
        raise BadRequest("'..' not allowed in plugin or script names")
    
    path = None
    for path_entry in c.plugin_path:
        if path_entry['name'] == plugin_location:
            path = path_entry
    
    if path is None:
        raise FileNotFound("Plugin location %s unknown" % (plugin_location))
        
    plugin = plugins.lookup_plugin(plugin_name, [path])
    if not plugin:
        response.status = "404 Not Found"
        response.content_type = "text/plain"
        response.body = "Plugin " + plugin_name + " does not exist"
        return response()
    
    # use the static package to actually serve the file
    newapp = static.Cling(plugin.location)
    request.path_info = "/" + "/".join(request.path_info.split("/")[5:])
    return newapp(request.environ, response.start_response)

@expose(r'^/plugin/reload/(?P<plugin_name>.+)', 'GET', auth=False)
def reload_plugin(request, response):
    response.content_type = "text/javascript"
    plugin_name = request.kwargs['plugin_name']
    if ".." in plugin_name:
        raise BadRequest("'..' not allowed in plugin names")
    if request.user:
        path = _get_user_plugin_path(request)
    else:
        path = []
    path.extend(c.plugin_path)
    
    plugin = plugins.lookup_plugin(plugin_name, path)
    
    return _plugin_response(response, plugin_list=[plugin])
    
def _wrap_script(plugin_name, script_path, script_text):
    if script_path:
        module_name = os.path.splitext(script_path)[0]
    else:
        module_name = "index"
        
    return """; tiki.module('%s:%s', function(require, exports, module) {%s
;}); tiki.script('%s:%s');""" % (plugin_name, module_name, 
        script_text, plugin_name, script_path)


def db_middleware(app):
    def wrapped(environ, start_response):
        from bespin import model
        from sqlalchemy.orm import scoped_session
        session = c.session_factory()
        environ['bespin.docommit'] = True
        try:
            # If you need to work out what <script> tags to insert into a
            # page to get Dojo to behave properly, then uncomment these 3
            # path_info = environ["PATH_INFO"]
            # if path_info.endswith(".js"):
            #     print "<script type='text/javascript' src='%s'></script>" % path_info

            result = app(environ, start_response)
            if result == None:
                log.error("WSGI response == None")
            if environ['bespin.docommit']:
                session.commit()
            else:
                session.rollback()
        except:
            session.rollback()
            c.stats.incr("exceptions_DATE")
            log.exception("Error raised during request: %s", environ)
            raise
        c.stats.disconnect()
        return result
    return wrapped

def pathpopper_middleware(app, num_to_pop=1):
    def new_app(environ, start_response):
        req = Request(environ)
        for i in range(0, num_to_pop):
            req.path_info_pop()
        return app(environ, start_response)
    return new_app

_separate_plugin_name = re.compile("/([^/]+):")

def scriptwrapper_middleware(app):
    def new_app(environ, start_response):
        req = Request(environ)
        if req.path_info.startswith("/getscript"):
            if ":" not in req.path_info:
                raise BadRequest(": delimiter required to separate plugin name from plugin file")
            req.path_info_pop()
            url_leading, plugin_name, script_path = _separate_plugin_name.split(req.path_info)
            if not script_path:
                req.path_info = req.path_info[:-1]
            else:
                req.path_info = req.path_info.replace(":", "/")
            plugin_name = plugin_name.replace(".js", "")
            process_script = True
        else:
            process_script = False
        result = req.get_response(app)
        if process_script and result.status.startswith("200"):
            contents = result.body
            newbody = _wrap_script(plugin_name, script_path, contents)
            result.headers['Content-Length'] = str(len(newbody))
            result.headers['Content-Type'] = "text/javascript"
            start_response(result.status, result.headers.items())
            return [newbody]
        start_response(result.status, result.headers.items())
        return [result.body]
    return new_app
    
class URLRelayCompatibleProxy(Proxy):
    """URLRelay deep copies items from its cache, but there's
    something on Paste's Proxy class that doesn't deepcopy
    safely. This class works fine."""
    
    def __deepcopy__(self, memo):
        return self

def make_app():
    from webob import Response
    static_app = static.Cling(c.static_dir)
    if c.static_override:
        from paste.cascade import Cascade
        static_app = Cascade([static.Cling(c.static_override), static_app])

    docs_app = pathpopper_middleware(static.Cling(c.docs_dir))
    code_app = pathpopper_middleware(static.Cling(c.static_dir + "/js"), 2)

    register("^/docs/code/", code_app)
    register("^/docs/", docs_app)
    
    proxy_app = URLRelayCompatibleProxy("http://localhost:8081/")
    register("^/.js/", proxy_app)
    
    for location, directory in c.static_map.items():
        topop = 1 + location.count('/')
        more_static = pathpopper_middleware(static.Cling(directory), topop)
        register("^/%s/" % location, more_static)

    app = URLRelay(default=static_app)
    app = auth_tkt.AuthTKTMiddleware(app, c.secret, secure=c.secure_cookie, 
                include_ip=False, httponly=c.http_only_cookie,
                current_domain_cookie=c.current_domain_cookie, wildcard_cookie=False)
    app = db_middleware(app)
    
    if c.log_requests_to_stdout:
        from paste.translogger import TransLogger
        app = TransLogger(app)
        
    app = scriptwrapper_middleware(app)
    return app
