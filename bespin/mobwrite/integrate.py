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

from bespin.database import User, get_project
import logging

log = logging.getLogger("mobwrite.integrate")


def get_username_from_handle(handle):
    """The handle added by the user (in controllers.py) is of the form
    {User.username}:{ip address}, which is what is expected for reporting on
    collaborators, but error messages just want the username part"""
    (requester, sep, ipstr) = handle.partition(':')
    return requester


class Access:
    """Constants for use by Persister"""
    Denied = 1
    ReadOnly = 2
    ReadWrite = 3


class Persister:
    """A plug-in for mobwrite_daemon that diverts calls to Bespin"""

    def load(self, name, handle):
        """Load a temporary file by extracting the project from the filename
        and calling project.get_temp_file"""
        try:
            (user, owner, project_name, path) = self._split_path(name, handle)
            project = get_project(user, owner, project_name)
            log.debug("loading temp file for: %s/%s" % (project.name, path))
            bytes = project.get_temp_file(path)
            # mobwrite gets things into unicode by doing bytes.encode("utf-8")
            # which uses the 'strict' error handling technique, which raises
            # on failure. Since we're not tracking content-type on the server
            # we could have anything at this point so, and we don't want to die
            # so we fudge the issue by ignoring things that are not utf-8
            return bytes.decode("utf-8", "ignore")
        except:
            log.exception("Error in Persister.load() for name=%s", name)
            return ""

    def save(self, name, contents, handle):
        """Load a temporary file by extracting the project from the filename
        and calling project.save_temp_file"""
        try:
            (user, owner, project_name, path) = self._split_path(name, handle)
            project = get_project(user, owner, project_name)
            log.debug("saving to temp file for: %s/%s" % (project.name, path))
            project.save_temp_file(path, contents)
        except:
            log.exception("Error in Persister.save() for name=%s", name)

    def check_access(self, name, handle):
        """Check to see what level of access user has over an owner's project.
        Returns one of: Access.Denied, Access.ReadOnly or Access.ReadWrite
        Note that if user==owner then no check of project_name is performed, and
        Access.ReadWrite is returned straight away"""
        try:
            (user, owner, project_name, path) = self._split_path(name, handle)
            if user == owner:
                return Access.ReadWrite
            if user != owner:
                if owner.is_project_shared(project_name, user, require_write=True):
                    return Access.ReadWrite
                if owner.is_project_shared(project_name, user, require_write=False):
                    return Access.ReadOnly
                else:
                    return Access.Denied
        except Error, e:
            log.exception("Error in Persister.check_access() for name=%s, handle=%s", 
                            name, handle)
            return Access.Denied

    def _split_path(self, path, handle):
        """Extract user, owner, project name, and path and return it as a tuple."""
        requester = get_username_from_handle(handle)
        user = User.find_user(requester)
        if path[0] == "/":
            path = path[1:]
        result = path.split('/', 1)
        parts = result[0].partition('+')
        if parts[1] == '':
            result.insert(0, user)
        else:
            result.insert(0, User.find_user(parts[0]))
            result[1] = parts[2]
        result.insert(0, user)
        return result
