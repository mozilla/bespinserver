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
