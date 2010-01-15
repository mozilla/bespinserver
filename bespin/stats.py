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

"""Methods for tracking statistics."""

from datetime import date
import logging

log = logging.getLogger("bespin.stats")

class DoNothingStats(object):
    def incr(self, key, by=1):
        return 0
        
    def decr(self, key, by=1):
        return 0
    
    def multiget(self, keys):
        return dict()
        
    def disconnect(self):
        pass

def _get_key(key):
    if "_DATE" in key:
        return key.replace("DATE", date.today().strftime("%Y%m%d"))
    return key

class MemoryStats(object):
    def __init__(self):
        self.storage = {}
        
    def incr(self, key, by=1):
        key = _get_key(key)
        current = self.storage.setdefault(key, 0)
        newval = current + by
        self.storage[key] = newval
        return newval
        
    def decr(self, key, by=1):
        return self.incr(key, -1*by)
    
    def multiget(self, keys):
        return dict((key, self.storage.get(key)) for key in keys)
        
    def disconnect(self):
        pass
        
class RedisStats(object):
    def __init__(self, redis):
        self.redis = redis
        
    def incr(self, key, by=1):
        key = _get_key(key)
        try:
            return self.redis.incr(key, by)
        except:
            log.exception("Problem incrementing stat %s", key)
    
    def decr(self, key, by=1):
        key = _get_key(key)
        try:
            return self.redis.decr(key, by)
        except:
            log.exception("Problem decrementing stat %s", key)
        
    def multiget(self, keys):
        return dict(zip(keys, self.redis.mget(*keys)))
    
    def disconnect(self):
        self.redis.disconnect()
        