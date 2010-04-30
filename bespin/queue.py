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

"""Functions for managing asynchronous operations."""
import sqlite3
import simplejson
import time
import logging
import sys

import urllib
import urllib2
import time

from bespin import config

try:
    import beanstalkc
except ImportError:
    pass

log = logging.getLogger("bespin.queue")

class QueueItem(object):
    next_jobid = 0

    def __init__(self, id, queue, message, execute, error_handler=None,
                job=None, use_db=True, origin=None):
        if id == None:
            self.id = QueueItem.next_jobid
            QueueItem.next_jobid = QueueItem.next_jobid + 1
        else:
            self.id = id
        self.queue = queue
        self.message = message
        self.execute = execute
        self.error_handler = error_handler
        self.job = job
        self.use_db = use_db
        self.origin = origin
        self.session = None

    def run(self):
        execute = self.execute
        execute = _resolve_function(execute)

        use_db = self.use_db
        if use_db:
            session = config.c.session_factory()
            self.session = session
        try:
            execute(self)
            if use_db:
                session.commit()
        except Exception, e:
            if use_db:
                session.rollback()
                session.close()

                # get a fresh session for the error handler to use
                session = config.c.session_factory()
                self.session = session

            try:
                self.error(e)
                if use_db:
                    session.commit()
            except:
                if use_db:
                    session.rollback()
                log.exception("Error in error handler for message %s. Original error was %s", self.message, e)
        finally:
            if use_db:
                session.close()
        return self.id

    def error(self, e):
        error_handler = self.error_handler
        error_handler = _resolve_function(error_handler)
        error_handler(self, e)

    def done(self):
        if self.origin == "beanstalk":
            if self.job:
                self.job.delete()
        elif self.origin == "restmq":
            if self.job:
                self.job.delete(self.queue, self.id)

class BeanstalkQueue(object):
    """Manages Bespin jobs within a beanstalkd server.

    http://xph.us/software/beanstalkd/

    The client library used is beanstalkc:

    http://github.com/earl/beanstalkc/tree/master
    """

    def __init__(self, host, port):
        if host is None or port is None:
            self.conn = beanstalkc.Connection()
        else:
            self.conn = beanstalkc.Connection(host=host, port=port)

    def enqueue(self, name, message, execute, error_handler, use_db):
        message['__execute'] = execute
        message['__error_handler'] = error_handler
        message['__use_db'] = use_db
        c = self.conn
        c.use(name)
        id = c.put(simplejson.dumps(message))
        return id

    def read_queue(self, name):
        c = self.conn
        log.debug("Starting to read %s on %s", name, c)
        c.watch(name)

        while True:
            log.debug("Reserving next job")
            item = c.reserve()
            if item is not None:
                log.debug("Job received (%s)", item.jid)
                message = simplejson.loads(item.body)
                execute = message.pop('__execute')
                error_handler = message.pop('__error_handler')
                use_db = message.pop('__use_db')
                qi = QueueItem(item.jid, name, message,
                                execute, error_handler=error_handler,
                                job=item, use_db=use_db, origin="beanstalk")
                yield qi

    def close(self):
        self.conn.close()

class RestMqQueue(object):
    """
    Manages Bespin jobs within a RestMQ server.

    http://github.com/gleicon/restmq
    """

    def __init__(self, host, port, timeout=0.3):
        self.host = host or "localhost"
        self.port = port or 8888
        self.timeout = timeout
        self.url = "http://" + self.host + ":" + self.port + "/queue"
        
    def _do_cmd(self, **kwargs):
        # special treatment of 'value'
        if 'value' in kwargs:
            kwargs['value'] = simplejson.dumps(kwargs['value'])
        req = urllib2.Request(
            self.url,
            urllib.urlencode({
                'body': simplejson.dumps(kwargs)
            })
        )
        rsp = urllib2.urlopen(req)
        obj = simplejson.loads(rsp.read())
        return obj

    def enqueue(self, name, message, execute, error_handler, use_db):
        message['__execute'] = execute
        message['__error_handler'] = error_handler
        message['__use_db'] = use_db
        obj = self._do_cmd(cmd="add", queue=name, value=message)
        return obj and obj['key'] or None

    def delete(name, id):
        return self._do_cmd(cmd="del", queue=name, key=id)

    def read_queue(self, name):
        log.debug("Starting to read %s on %s", name, self.url)
        while True:
            log.debug("Reserving next job")
            item = self._do_cmd(cmd="get", queue=name)
            if item is None or ('error' in item):
                time.sleep(self.timeout)
                continue
            log.debug("Job received (%s)", item['key'])
            message = simplejson.loads(item['value'])
            execute = message.pop('__execute')
            error_handler = message.pop('__error_handler')
            use_db = message.pop('__use_db')
            qi = QueueItem(item['key'], name, message,
                            execute, error_handler=error_handler,
                            job=self, use_db=use_db, origin="restmq")
            yield qi

    def close(self):
        # don't need to close anything
        pass

def _resolve_function(namestring):
    modulename, funcname = namestring.split(":")
    module = __import__(modulename, fromlist=[funcname])
    return getattr(module, funcname)

def enqueue(queue_name, message, execute, error_handler=None, use_db=True):
    if config.c.queue:
        id = config.c.queue.enqueue(queue_name, message, execute,
                                    error_handler, use_db)
        log.debug("Running job asynchronously (%s)", id)
        return id
    else:
        qi = QueueItem(None, queue_name, message, execute,
                        error_handler=error_handler, use_db=use_db)
        log.debug("Running job synchronously (%s)", qi.id)
        return qi.run()

def process_queue(args=None):
    log.info("Bespin queue worker")
    if args is None:
        args = sys.argv[1:]

    if args:
        config.set_profile(args.pop(0))
    else:
        config.set_profile("dev")
        config.c.async_jobs=True

    if args:
        config.load_pyconfig(args.pop(0))

    config.activate_profile()

    bq = config.c.queue
    log.debug("Queue: %s", bq)
    for qi in bq.read_queue("vcs"):
        log.info("Processing job %s", qi.id)
        log.debug("Message: %s", qi.message)
        qi.run()
        qi.done()
