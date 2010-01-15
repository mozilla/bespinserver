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

"""Failed login tracking.

Keep track of the number of failed attempts to log in per user over a given time
period. If there are too many failed login attempts during that period, the user
will be locked out.
"""

import time

class FailedLoginInfo(object):
    def __init__(self, username, can_log_in, failed_attempts):
        self.username = username
        self.can_log_in = can_log_in
        self.failed_attempts = failed_attempts

class DoNothingFailedLoginTracker(object):
    def can_log_in(self, username):
        """Returns FailedLoginInfo. Check the return result.can_log_in to
        verify that the user is allowed to log in."""
        return FailedLoginInfo(username, True, 0)
        
    def login_failed(self, fli):
        """Pass in the FailedLoginInfo from can_log_in and a failed login
        attempt will be tracked."""
        pass
        
    def login_successful(self, fli):
        """Pass in the FailedLoginInfo from can_log_in and the successful
        login will be tracked."""
        pass
    
class MemoryFailedLoginTracker(object):
    """Stores the information in memory. This is really only for development/testing
    purposes. You would not use this in production. The failed logins are not
    automatically expired."""
    
    def __init__(self, number_of_attempts, lockout_period):
        self.number_of_attempts = number_of_attempts
        self.lockout_period = lockout_period
        self.store = {}
        
    def can_log_in(self, username):
        now = time.time()
        current = self.store.get(username, [0, now])
        if now > current[1]:
            # reset if we've passed the time out
            current = [0, 0]
            del self.store[username]
            
        if current[0] >= self.number_of_attempts:
            return FailedLoginInfo(username, False, current[0])
        return FailedLoginInfo(username, True, current[0])
        
    def login_failed(self, fli):
        current = self.store.setdefault(fli.username, [0, 0])
        current[0] += 1
        current[1] = time.time() + self.lockout_period
        
    def login_successful(self, fli):
        try:
            del self.store[fli.username]
        except KeyError:
            pass
        
        