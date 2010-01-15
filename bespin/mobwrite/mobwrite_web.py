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

import sys
import logging

from paste.httpserver import serve
from webob import Request, Response

from bespin.mobwrite.mobwrite_daemon import DaemonMobWrite
from bespin import config
from bespin.controllers import db_middleware

log = logging.getLogger("mw_web")

class WSGIMobWrite(DaemonMobWrite):
    def __call__(self, environ, start_response):
        request = Request(environ)
        response = Response()
        try:
            answer = self.handleRequest(request.body)
            response.body = answer
            response.content_type = "application/mobwrite"
        except Exception, e:
            log.exception("error in request handling")
            response.status = "500 Internal Server Error"
            response.body = str(e)
        return response(environ, start_response)

def start_server(args=None):
    if args is None:
        args = sys.argv[1:]

    if args:
        mode = args.pop(0)
    else:
        mode = "dev"

    print("Bespin mobwrite worker (mode=" + mode + ")")  
    config.set_profile(mode)

    if args:
        config.load_pyconfig(args.pop(0))

    if mode == "dev":
        config.load_pyconfig("devconfig.py")

    config.activate_profile()

    app = WSGIMobWrite()
    app = db_middleware(app)

    serve(app, config.c.mobwrite_server_address, config.c.mobwrite_server_port, use_threadpool=True)
