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

import os
import time
from cStringIO import StringIO
from urllib import quote
from traceback import format_exc
import logging

from simplejson import dumps, loads
from omnisync.main import OmniSync
from omnisync.configuration import Configuration

from bespin.vcs import KeyChain, TempSSHKeyFile
from bespin import queue
from bespin.filesystem import get_project
from bespin.database import User, Message, _get_session


log = logging.getLogger("bespin.deploy")

# Ideally, we would have a better "remote server" abstraction than this!
class DeploymentKeyChain(KeyChain):
    """A keychain with deployment-specific information."""
    
    def set_ssh_for_project(self, project, username):
        """Saves the fact that SSH keys are being used for
        deployment of this project. Returns the public key."""
        kcdata = self.kcdata
        pubkey = self.get_ssh_key()
        deployments = kcdata.setdefault("deploy", {})
        deployments[project.full_name] = dict(type="ssh",
            username=username)
        
        self._save()
        
    def set_credentials_for_project(self, project, username, 
                                    password):
        """Stores the username/password credentials for this project."""
        kcdata = self.kcdata
        deployments = kcdata.setdefault("deploy", {})
        deployments[project.full_name] = dict(type="password",
            username=username, password=password)
            
        self._save()
    
    def get_credentials_for_project(self, project):
        """Returns a dictionary with the user's information for
        the given project. The dictionary will have 'type'
        with values 'ssh', or 'password'. If the type is ssh,
        there will be an ssh_key entry. If the type is password,
        there will be username and password entries. If there
        are no credentials stored for the given project,
        None is returned."""
        kcdata = self.kcdata
        deployments = kcdata.setdefault("deploy", {})
        
        value = deployments.get(project.full_name)
        
        if value is not None:
            # we're going to make a copy of the data so that it
            # doesn't get mutated against our wishes
            value = dict(value)
        
            # for SSH, we need to change the SSH key name into the key itself.
            if value['type'] == "ssh":
                value['ssh_private_key'] = kcdata['ssh']['private']
                value['ssh_public_key'] = kcdata['ssh']['public']
        
        return value

    def delete_credentials_for_project(self, project):
        """Forget the authentication information provided
        for the given project. Note that this will not
        remove any SSH keys used by the project."""
        kcdata = self.kcdata
        deployments = kcdata.setdefault("deploy", {})
        try:
            del deployments[project.full_name]
        except KeyError:
            pass
        
        self._save()
        
class ProjectDeploymentOptions(object):
    """Manages the deployment options for a project."""
    
    supported_types = set(['sftp'])
    
    @classmethod
    def get(cls, project):
        """Retrieve the deployment options for this project.
        Returns None if the options aren't set."""
        md = project.metadata
        info_json = md.get("deployment")
        if info_json is None:
            return None
        info_json = loads(info_json)
        # keyword argument names must be str objects, not unicode
        kw = dict((key.encode("ascii"), value) 
            for key, value in info_json.items())
        return cls(project, **kw)
    
    def __init__(self, project, remote_host, remote_directory, type):
        if type not in self.supported_types:
            raise InvalidConfiguration("Type must be one of %s" %
                (",".join(self.supported_types)))
        self.project = project
        self.remote_host = remote_host
        self.remote_directory = remote_directory
        self.type = type
        
    def save(self):
        """Save the options in the project metadata."""
        md = self.project.metadata
        info_dict = dict(remote_host = self.remote_host,
            remote_directory = self.remote_directory,
            type = self.type)
        md["deployment"] = dumps(info_dict)
    
# Deployment-specific Exceptions 

class NotConfigured(Exception):
    pass

class InvalidConfiguration(Exception):
    pass

class OmniSyncExit(Exception):
    def __init__(self, return_code):
        super(OmniSyncExit, self).__init__()
        self.return_code = return_code
    
def deploy_error(qi, e):
    """Handles errors that come up during deployment."""
    log.debug("Handling deploy error: %s", e)
    s = _get_session()
    user = qi.message['user']
    # if the user hadn't already been looked up, go ahead and pull
    # them out of the database
    if isinstance(user, basestring):
        user = User.find_user(user)
    else:
        s.add(user)
    
    # if we didn't find the user in the database, there's not much
    # we can do.
    if user:
        # it looks like a programming error and we
        # want more information
        tb = format_exc()
        print "E:", tb
        message = dict(jobid=qi.id, output=dict(output=tb, 
            error=True))
        message['asyncDone'] = True
        retval = Message(user_id=user.id, message=dumps(message))
        s.add(retval)
    
def run_deploy(user, project, kcpass, options):
    """Add the deployment request to the worker queue."""
    pdo = ProjectDeploymentOptions.get(project)
    if not pdo:
        raise NotConfigured("Deployment is not yet configured.")
    user = user.username
    project = project.name
    job_body = dict(user=user, project=project, kcpass=kcpass, 
                    options=options)
    return queue.enqueue("vcs", job_body, execute="bespin.deploy:deploy_impl",
                        error_handler="bespin.deploy:deploy_error",
                        use_db=True)
    
def deploy_impl(qi):
    """Executed via the worker queue to actually deploy the
    project."""
    message = qi.message
    kcpass = message['kcpass']
    options = _OptionHolder(message['options'])
    
    s = _get_session()
    
    user = User.find_user(message['user'])
    project = get_project(user, user, message['project'])
    pdo = ProjectDeploymentOptions.get(project)
    keychain = DeploymentKeyChain(user, kcpass)
    credentials = keychain.get_credentials_for_project(project)
    cwd = os.getcwd()
    
    keyfile = None
    
    options.username = credentials['username']

    if credentials['type'] == 'ssh':
        keyfile = TempSSHKeyFile()
        keyfile.store(credentials['ssh_public_key'], 
                      credentials['ssh_private_key'])
        options.sshkey = keyfile.filename
    else:
        options.password = credentials['password']
        
    desturl = "sftp://%s/%s" % (quote(pdo.remote_host, safe=""),
        quote(pdo.remote_directory))
        
    try:
        os.chdir(project.location)
        log.debug("Computed destination URL: %s", desturl)
        log.debug("Running with options: %r", options)
        error, output = _launch_sync(qi.id, user.id, desturl, options)
        
        # there's an extra layer around the output that is
        # expected by the client
        result = dict(output=dict(output=output, error=error))

        result.update(dict(jobid=qi.id, asyncDone=True))
        retvalue = Message(user_id=user.id, message=dumps(result))
        s.add(retvalue)
    finally:
        if keyfile:
            keyfile.delete()
        os.chdir(cwd)
        
    

class _OptionHolder(object):
    """Mimics the command line options for OmniSync."""
    verbosity = 1
    delete = False
    attributes = []
    dry_run = False
    update = False
    recursive = True
    exclude_files = []
    include_files = []
    exclude_dirs = r"\.svn|\.hg|\.git|\.bzr"
    include_dirs = []
    
    # because Bespin is a shared environment, we cannot reasonably
    # set these values on the remote system
    exclude_attributes = set(["owner", "group", "perms"])
    
    def __init__(self, opts):
        for key, value in opts.items():
            setattr(self, key, value)
        
    def repr(self):
        return repr(self.__dict__)
    
class BespinOmniSync(OmniSync):
    def __init__(self, qid, user_id, *args, **kw):
        super(BespinOmniSync, self).__init__(*args, **kw)
        self.qid = qid
        self.user_id = user_id
        self.output_stream = StringIO()
        self.handler = logging.StreamHandler(self.output_stream)
        self.handler.setLevel(logging.INFO)
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.log = logging.getLogger("omnisync")
        self.log.setLevel(logging.INFO)
        self.log.addHandler(self.handler)
        self.last_display_time = 0
    
    def file_done(self):
        super(BespinOmniSync, self).file_done()
        if time.time() - self.last_display_time > 5:
            s = _get_session()
            message_body = dict(jobid=self.qid, asyncDone=False, 
                output="%s files and %s bytes copied" % (
                    self.file_counter, self.bytes_total))
            message = Message(user_id = self.user_id,
                message=dumps(message_body))
            s.add(message)
            s.commit()
            
            self.last_display_time = time.time()
        
    def get_output(self):
        return self.output_stream.getvalue()
        
    def cleanup(self):
        self.log.removeHandler(self.handler)
        self.output_stream = None
        
    def report_file_progress(self, prog, bytes_done):
        pass
        
    def exit(self, return_code):
        raise OmniSyncExit(return_code)
    
def _launch_sync(qid, user_id, desturl, options):
    omnisync = BespinOmniSync(qid, user_id)
    omnisync.config = Configuration(options)
    
    try:
        omnisync.sync(".", desturl)
        error = False
    except OmniSyncExit, e:
        if e.return_code:
            error = True
        else:
            error = False
            
    output = omnisync.get_output()
    omnisync.cleanup()
    return error, output
    