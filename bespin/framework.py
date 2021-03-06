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

from urlrelay import url
from webob import Request, Response
import logging

from bespin import filesystem, database, config, plugins
from bespin.__init__ import API_VERSION
from bespin.database import User

log = logging.getLogger("bespin.framework")

class BadRequest(Exception):
    pass

class BespinRequest(Request):
    """Custom request object for Bespin.

    Provides the user object and the username of the
    logged in user, among other features."""
    def __init__(self, environ):
        super(BespinRequest, self).__init__(environ)

        if 'bespin.user' in environ:
            self._user = environ['bespin.user']
        else:
            self._user = None
        self.username = environ.get('REMOTE_USER')
        self.kwargs = environ.get('wsgiorg.routing_args')[1]
        self.session_token = environ.get("HTTP_X_DOMAIN_TOKEN")

    @property
    def user(self):
        if self._user:
            return self._user
        if self.username:
            self._user = User.find_user(self.username)
            return self._user
        return None

class BespinResponse(Response):
    def __init__(self, environ, start_response, **kw):
        super(BespinResponse, self).__init__(**kw)
        self.environ = environ
        self.start_response = start_response

    def __call__(self):
        return super(BespinResponse, self).__call__(self.environ, self.start_response)

    def error(self, status, e):
        self.status = status
        self.body = str(e)
        self.environ['bespin.docommit'] = False

def _add_base_headers(response):
    response.headers['X-Bespin-API'] = API_VERSION
    response.headers['Cache-Control'] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, private"
    response.headers['Pragma'] = "no-cache"

def expose(url_pattern, method=None, auth=True, skip_token_check=False, profile=False):
    """Expose this function to the world, matching the given URL pattern
    and, optionally, HTTP method. By default, the user is required to
    be authenticated. If auth is False, the user is not required to be
    authenticated."""
    def entangle(func):
        @url(url_pattern, method)
        def wrapped(environ, start_response):

            # reply and action are somewhat nasty but needed to allow the
            # profiler to run code by a "action()" string. Why?
            reply = []
            def action():
                if auth and 'REMOTE_USER' not in environ:
                    response = Response(status='401')
                    _add_base_headers(response)
                    reply.append(response(environ, start_response))
                    return

                config.c.stats.incr("requests_DATE")
                config.c.stats.incr("requests")

                request = BespinRequest(environ)
                response = BespinResponse(environ, start_response)
                skip_test = environ.get("BespinTestApp")

                if not skip_token_check and skip_test != "True":
                    cookie_token = request.cookies.get("Domain-Token")
                    header_token = environ.get("HTTP_X_DOMAIN_TOKEN")

                    if cookie_token is None or header_token != cookie_token:
                        # log.info("request.url=%s" % request.url)
                        # log.info("cookies[Domain-Token]=%s" % cookie_token)
                        # log.info("headers[X-Domain-Token]=%s" % header_token)
                        # log.info("WARNING: The anti CSRF attack trip wire just went off. This means an unprotected request has been made. This could be a hacking attempt, or incomplete protection. The request has NOT been halted")
                        config.c.stats.incr("csrf_fail_DATE")

                # Do we need to do this?
                user = request.user
                _add_base_headers(response)
                try:
                    reply.append(func(request, response))
                    return
                except filesystem.NotAuthorized, e:
                    response.error("401 Not Authorized", e)
                except filesystem.FileNotFound, e:
                    environ['bespin.good_url_but_not_found'] = True
                    response.error("404 Not Found", e)
                except filesystem.FileConflict, e:
                    response.error("409 Conflict", e)
                except database.ConflictError, e:
                    response.error("409 Conflict", e)
                except filesystem.OverQuota, e:
                    response.error("400 Bad Request", "Over quota")
                except filesystem.FSException, e:
                    response.error("400 Bad Request", e)
                except filesystem.BadValue, e:
                    response.error("400 Bad Request", e)
                except plugins.PluginError, e:
                    response.error("400 Bad Request", e)
                except BadRequest, e:
                    response.error("400 Bad Request", e)
                reply.append(response())
                return

            if profile:
                # The output probably needs tuning for your needs
                import cProfile, pstats, StringIO
                prof = cProfile.Profile()
                prof = prof.runctx("action()", globals(), locals())
                stream = StringIO.StringIO()
                stats = pstats.Stats(prof, stream=stream)
                stats.sort_stats("time")  # Or cumulative
                stats.print_stats(80)  # 80 = how many to print
                # The rest is optional.
                stats.print_callees()
                stats.print_callers()
                log.info("Profile data:\n%s", stream.getvalue())
            else:
                action()

            return reply.pop()

    return entangle

