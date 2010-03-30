#!/usr/bin/python
"""MobWrite - Real-time Synchronization and Collaboration Service

Copyright 2006 Google Inc.
http://code.google.com/p/google-mobwrite/

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

"""This file is the server-side daemon.

Runs in the background listening to a port, accepting synchronization sessions
from clients.
"""

__author__ = "fraser@google.com (Neil Fraser)"

import datetime
import glob
import os
import socket
import SocketServer
import sys
import time
import thread
import urllib
import simplejson

import mobwrite_core
from bespin.mobwrite.integrate import Persister, Access, get_username_from_handle

# Demo usage should limit the maximum number of connected views.
# Set to 0 to disable limit.
MAX_VIEWS = 10000

# How should data be stored.
MEMORY = 0
FILE = 1
BDB = 2
PERSISTER = 3
STORAGE_MODE = PERSISTER

# Port to listen on.
LOCAL_PORT = 3017

# If the Telnet connection stalls for more than 2 seconds, give up.
TIMEOUT_TELNET = 2.0

# Restrict all Telnet connections to come from this location.
# Set to "" to allow connections from anywhere.
CONNECTION_ORIGIN = "127.0.0.1"

# Dictionary of all text objects.
texts = {}

# Berkeley Databases
texts_db = None
lasttime_db = None

# Lock to prevent simultaneous changes to the texts dictionary.
lock_texts = thread.allocate_lock()

# A special mode to save on every change which should reduce the impact of
# server crashes and restarts at the expense of server-load
PARANOID_SAVE = True

class TextObj(mobwrite_core.TextObj):
  # A persistent object which stores a text.

  # Object properties:
  # .lock - Access control for writing to the text on this object.
  # .views - Views currently connected to this text.
  # .lasttime - The last time that this text was modified.

  # Inherited properties:
  # .name - The unique name for this text, e.g 'proposal'.
  # .text - The text itself.
  # .changed - Has the text changed since the last time it was saved.

  def __init__(self, *args, **kwargs):
    # Setup this object
    mobwrite_core.TextObj.__init__(self, *args, **kwargs)
    self.persister = kwargs.get("persister")
    self.handle = kwargs.get("handle")
    self.views = []
    self.lasttime = datetime.datetime.now()
    self.lock = thread.allocate_lock()
    self.load()

    # lock_texts must be acquired by the caller to prevent simultaneous
    # creations of the same text.
    assert lock_texts.locked(), "Can't create TextObj unless locked."
    global texts
    texts[self.name] = self


  def __str__(self):
    return "TextObj[len(text)=" + str(len(self.text)) + ", chgd=" + str(self.changed) + ", len(views)=" + str(len(self.views)) + "]"


  def setText(self, newText, justLoaded=False):
    mobwrite_core.TextObj.setText(self, newText)
    self.lasttime = datetime.datetime.now()
    if self.changed and PARANOID_SAVE and not justLoaded:
      if self.lock.locked():
        self.save()
      else:
        self.lock.acquire()
        try:
          self.save()
        finally:
          self.lock.release()

  def cleanup(self):
    # General cleanup task.
    if len(self.views) > 0:
      return
    terminate = False
    # Lock must be acquired to prevent simultaneous deletions.
    mobwrite_core.LOG.debug("text.lock.acquire on %s", self.name)
    self.lock.acquire()
    try:
      if STORAGE_MODE == MEMORY:
        if self.lasttime < datetime.datetime.now() - mobwrite_core.TIMEOUT_TEXT:
          mobwrite_core.LOG.info("Expired text: '%s'" % self.name)
          terminate = True
      else:
        # Delete myself from memory if there are no attached views.
        mobwrite_core.LOG.info("Unloading text: '%s'" % self.name)
        terminate = True

      if terminate:
        # Save to disk/database.
        self.save()
        # Terminate in-memory copy.
        global texts
        mobwrite_core.LOG.debug("lock_texts.acquire")
        lock_texts.acquire()
        try:
          del texts[self.name]
        except KeyError:
          mobwrite_core.LOG.error("Text object not in text list: '%s'" % self.name)
        finally:
          mobwrite_core.LOG.debug("lock_texts.release")
          lock_texts.release()
      else:
        if self.changed:
          self.save()
    finally:
      mobwrite_core.LOG.debug("text.lock.release on %s", self.name)
      self.lock.release()


  def load(self):
    # Load the text object from non-volatile storage.
    if STORAGE_MODE == PERSISTER:
      contents = self.persister.load(self.name, self.handle)
      self.setText(contents, justLoaded=True)
      self.changed = False

    if STORAGE_MODE == FILE:
      # Load the text (if present) from disk.
      filename = "%s/%s.txt" % (DATA_DIR, urllib.quote(self.name, ""))
      if os.path.exists(filename):
        try:
          infile = open(filename, "r")
          self.setText(infile.read().decode("utf-8"))
          infile.close()
          self.changed = False
          mobwrite_core.LOG.info("Loaded file: '%s'" % filename)
        except:
          mobwrite_core.LOG.critical("Can't read file: %s" % filename)
      else:
        self.setText(None)
        self.changed = False

    if STORAGE_MODE == BDB:
      # Load the text (if present) from database.
      if texts_db.has_key(self.name):
        self.setText(texts_db[self.name].decode("utf-8"))
        mobwrite_core.LOG.info("Loaded from DB: '%s'" % self.name)
      else:
        self.setText(None)
      self.changed = False


  def save(self):
    # Save the text object to non-volatile storage.
    # Lock must be acquired by the caller to prevent simultaneous saves.
    assert self.lock.locked(), "Can't save unless locked."

    if STORAGE_MODE == PERSISTER:
      self.persister.save(self.name, self.text, self.handle)
      self.changed = False

    if STORAGE_MODE == FILE:
      # Save the text to disk.
      filename = "%s/%s.txt" % (DATA_DIR, urllib.quote(self.name, ''))
      if self.text is None:
        # Nullified text equates to no file.
        if os.path.exists(filename):
          try:
            os.remove(filename)
            mobwrite_core.LOG.info("Nullified file: '%s'" % filename)
          except:
            mobwrite_core.LOG.critical("Can't nullify file: %s" % filename)
      else:
        try:
          outfile = open(filename, "w")
          outfile.write(self.text.encode("utf-8"))
          outfile.close()
          self.changed = False
          mobwrite_core.LOG.info("Saved file: '%s'" % filename)
        except:
          mobwrite_core.LOG.critical("Can't save file: %s" % filename)

    if STORAGE_MODE == BDB:
      # Save the text to database.
      if self.text is None:
        if lasttime_db.has_key(self.name):
          del lasttime_db[self.name]
        if texts_db.has_key(self.name):
          del texts_db[self.name]
          mobwrite_core.LOG.info("Nullified from DB: '%s'" % self.name)
      else:
        mobwrite_core.LOG.info("Saved to DB: '%s'" % self.name)
        texts_db[self.name] = self.text.encode("utf-8")
        lasttime_db[self.name] = str(int(time.time()))
      self.changed = False


def fetch_textobj(name, view, persister, handle):
  # Retrieve the named text object.  Create it if it doesn't exist.
  # Add the given view into the text object's list of connected views.
  # Don't let two simultaneous creations happen, or a deletion during a
  # retrieval.
  mobwrite_core.LOG.debug("lock_texts.acquire")
  lock_texts.acquire()
  try:
    if texts.has_key(name):
      textobj = texts[name]
      mobwrite_core.LOG.debug("Accepted text: '%s'" % name)
    else:
      textobj = TextObj(name=name, persister=persister, handle=handle)
      mobwrite_core.LOG.debug("Creating text: '%s'" % name)
    textobj.views.append(view)
  finally:
    mobwrite_core.LOG.debug("lock_texts.release")
    lock_texts.release()
  return textobj


# Dictionary of all view objects.
views = {}

# Lock to prevent simultaneous changes to the views dictionary.
lock_views = thread.allocate_lock()

class ViewObj(mobwrite_core.ViewObj):
  # A persistent object which contains one user's view of one text.

  # Object properties:
  # .edit_stack - List of unacknowledged edits sent to the client.
  # .lasttime - The last time that a web connection serviced this object.
  # .lock - Access control for writing to the text on this object.
  # .textobj - The shared text object being worked on.

  # Inherited properties:
  # .username - The name for the user, e.g 'fraser'
  # .filename - The name for the file, e.g 'proposal'
  # .shadow - The last version of the text sent to client.
  # .backup_shadow - The previous version of the text sent to client.
  # .shadow_client_version - The client's version for the shadow (n).
  # .shadow_server_version - The server's version for the shadow (m).
  # .backup_shadow_server_version - the server's version for the backup
  #     shadow (m).

  def __init__(self, *args, **kwargs):
    # Setup this object
    mobwrite_core.ViewObj.__init__(self, *args, **kwargs)
    self.handle = kwargs.get("handle")
    self.metadata = kwargs.get("metadata")
    self.edit_stack = []
    self.lasttime = datetime.datetime.now()
    self.lock = thread.allocate_lock()
    self.textobj = fetch_textobj(self.filename, self, kwargs.get("persister"), kwargs.get("handle"))

    # lock_views must be acquired by the caller to prevent simultaneous
    # creations of the same view.
    assert lock_views.locked(), "Can't create ViewObj unless locked."
    global views
    views[(self.username, self.filename)] = self


  def __str__(self):
    return "ViewObj[scv=" + str(self.shadow_client_version) + ", ssv=" + str(self.shadow_server_version) + ", handle=" + self.handle + ", textobj.name=" + self.textobj.name + "]"


  def cleanup(self):
    # General cleanup task.
    # Delete myself if I've been idle too long.
    # Don't delete during a retrieval.
    mobwrite_core.LOG.debug("lock_views.acquire")
    lock_views.acquire()
    try:
      if self.lasttime < datetime.datetime.now() - mobwrite_core.TIMEOUT_VIEW:
        mobwrite_core.LOG.info("Idle out: '%s@%s'" % (self.username, self.filename))
        global views
        try:
          del views[(self.username, self.filename)]
        except KeyError:
          mobwrite_core.LOG.error("View object not in view list: '%s %s'" % (self.username, self.filename))
        try:
          self.textobj.views.remove(self)
        except ValueError:
          mobwrite_core.LOG.error("self not in views list: '%s %s'" % (self.username, self.filename))
    finally:
      mobwrite_core.LOG.debug("lock_views.release")
      lock_views.release()

  def nullify(self):
    self.lasttime = datetime.datetime.min
    self.cleanup()


def fetch_viewobj(username, filename, handle=None, metadata=None, persister=None):
  # Retrieve the named view object.  Create it if it doesn't exist.
  # Don't let two simultaneous creations happen, or a deletion during a
  # retrieval.
  mobwrite_core.LOG.debug("lock_views.acquire")
  lock_views.acquire()
  try:
    key = (username, filename)
    if views.has_key(key):
      viewobj = views[key]
      viewobj.lasttime = datetime.datetime.now()
      viewobj.metadata = metadata
      mobwrite_core.LOG.debug("Accepting view: '%s@%s'" % key)
    else:
      if MAX_VIEWS != 0 and len(views) > MAX_VIEWS:
        viewobj = None
        mobwrite_core.LOG.critical("Overflow: Can't create new view.")
      else:
        viewobj = ViewObj(username=username, filename=filename, handle=handle, metadata=metadata, persister=persister)
        mobwrite_core.LOG.debug("Creating view: '%s@%s'" % key)
  finally:
    mobwrite_core.LOG.debug("lock_views.release")
    lock_views.release()
  return viewobj


# Dictionary of all buffer objects.
buffers = {}

# Lock to prevent simultaneous changes to the buffers dictionary.
lock_buffers = thread.allocate_lock()

class BufferObj:
  # A persistent object which assembles large commands from fragments.

  # Object properties:
  # .name - The name (and size) of the buffer, e.g. 'alpha:12'
  # .lasttime - The last time that a web connection wrote to this object.
  # .data - The contents of the buffer.
  # .lock - Access control for writing to the text on this object.

  def __init__(self, name, size):
    # Setup this object
    self.name = name
    self.lasttime = datetime.datetime.now()
    self.lock = thread.allocate_lock()

    # Initialize the buffer with a set number of slots.
    # Null characters form dividers between each slot.
    array = []
    for x in xrange(size - 1):
      array.append("\0")
    self.data = "".join(array)

    # lock_buffers must be acquired by the caller to prevent simultaneous
    # creations of the same view.
    assert lock_buffers.locked(), "Can't create BufferObj unless locked."
    global buffers
    buffers[name] = self
    mobwrite_core.LOG.debug("Buffer initialized to %d slots: %s" % (size, name))

  def __str__(self):
    return "BufferObj[name=" + self.name + ", len(data)=" + len(self.data) + "]"


  def set(self, n, text):
    # Set the nth slot of this buffer with text.
    assert self.lock.locked(), "Can't edit BufferObj unless locked."
    # n is 1-based.
    n -= 1
    array = self.data.split("\0")
    assert 0 <= n < len(array), "Invalid buffer insertion"
    array[n] = text
    self.data = "\0".join(array)
    mobwrite_core.LOG.debug("Inserted into slot %d of a %d slot buffer: %s" %
        (n + 1, len(array), self.name))

  def get(self):
    # Fetch the completed text from the buffer.
    if ("\0" + self.data + "\0").find("\0\0") == -1:
      text = self.data.replace("\0", "")
      # Delete this buffer.
      self.lasttime = datetime.datetime.min
      self.cleanup()
      return text
    # Not complete yet.
    return None

  def cleanup(self):
    # General cleanup task.
    # Delete myself if I've been idle too long.
    # Don't delete during a retrieval.
    mobwrite_core.LOG.debug("lock_buffers.acquire")
    lock_buffers.acquire()
    try:
      if self.lasttime < datetime.datetime.now() - mobwrite_core.TIMEOUT_BUFFER:
        mobwrite_core.LOG.info("Expired buffer: '%s'" % self.name)
        global buffers
        del buffers[self.name]
    finally:
      mobwrite_core.LOG.debug("lock_buffers.release")
      lock_buffers.release()


class DaemonMobWrite(mobwrite_core.MobWrite):
  def __init__(self):
    self.persister = Persister()

  def handleRequest(self, text):
    try:
      mobwrite_core.LOG.debug("Incoming: " + text)
      actions = self.parseRequest(text)
      reply = self.doActions(actions)
      mobwrite_core.LOG.debug("Reply: " + reply)
      return reply
    except:
      mobwrite_core.LOG.exception("Error handling request: " + text)
      return "E:all:Processing error"

  def doActions(self, actions):
    output = []
    last_username = None
    last_filename = None

    for action_index in xrange(len(actions)):
      action = actions[action_index]
      mobwrite_core.LOG.debug("action %s = %s", action_index, action)

    for action_index in xrange(len(actions)):
      # Use an indexed loop in order to peek ahead one step to detect
      # username/filename boundaries.
      action = actions[action_index]

      # Close mode doesn't need a filename or handle for the 'close all' case
      # If killing a specific view, then the id is in the 'data'
      if action["mode"] == "close":
        to_close = action.get("data")
        if to_close == "all":
          kill_views_for_user(action["username"])
        elif to_close is not None:
          kill_view(action["username"], to_close)
        continue

      viewobj = fetch_viewobj(action["username"], action["filename"], handle=action["handle"], metadata=action["metadata"], persister=self.persister)
      if viewobj is None:
        # Too many views connected at once.
        # Send back nothing.  Pretend the return packet was lost.
        return ""

      delta_ok = True
      mobwrite_core.LOG.debug("view.lock.acquire on %s@%s", viewobj.username, viewobj.filename)
      viewobj.lock.acquire()
      textobj = viewobj.textobj

      try:
        access = self.persister.check_access(action["filename"], action["handle"])
        if access == Access.Denied:
          name = get_username_from_handle(action["handle"])
          message = "%s does not have access to %s" % (name, action["filename"])
          mobwrite_core.LOG.warning(message)
          output.append("E:" + action["filename"] + ":" + message + "\n")
          continue

        if action["mode"] == "null":
          if access == Access.ReadOnly:
            output.append("O:" + action["filename"] + "\n")
          else:
            # Nullify the text.
            mobwrite_core.LOG.debug("Nullifying: '%s@%s'" %
                (viewobj.username, viewobj.filename))
            mobwrite_core.LOG.debug("text.lock.acquire on %s", textobj.name)
            textobj.lock.acquire()
            try:
              textobj.setText(None)
            finally:
              mobwrite_core.LOG.debug("text.lock.release on %s", textobj.name)
              textobj.lock.release()
            viewobj.nullify()
          continue

        if (action["server_version"] != viewobj.shadow_server_version and
            action["server_version"] == viewobj.backup_shadow_server_version):
          # Client did not receive the last response.  Roll back the shadow.
          mobwrite_core.LOG.warning("Rollback from shadow %d to backup shadow %d" %
              (viewobj.shadow_server_version, viewobj.backup_shadow_server_version))
          viewobj.shadow = viewobj.backup_shadow
          viewobj.shadow_server_version = viewobj.backup_shadow_server_version
          viewobj.edit_stack = []

        # Remove any elements from the edit stack with low version numbers which
        # have been acked by the client.
        x = 0
        while x < len(viewobj.edit_stack):
          if viewobj.edit_stack[x][0] <= action["server_version"]:
            del viewobj.edit_stack[x]
          else:
            x += 1

        if action["mode"] == "raw":
          # It's a raw text dump.
          data = urllib.unquote(action["data"]).decode("utf-8")
          mobwrite_core.LOG.info("Got %db raw text: '%s@%s'" %
              (len(data), viewobj.username, viewobj.filename))
          delta_ok = True
          # First, update the client's shadow.
          viewobj.shadow = data
          viewobj.shadow_client_version = action["client_version"]
          viewobj.shadow_server_version = action["server_version"]
          viewobj.backup_shadow = viewobj.shadow
          viewobj.backup_shadow_server_version = viewobj.shadow_server_version
          viewobj.edit_stack = []
          if access == Access.ReadOnly:
            output.append("O:" + action["filename"] + "\n")
          elif action["force"] or textobj.text == None:
            # Clobber the server's text.
            mobwrite_core.LOG.debug("text.lock.acquire on %s", textobj.name)
            textobj.lock.acquire()
            try:
              if textobj.text != data:
                textobj.setText(data)
                mobwrite_core.LOG.debug("Overwrote content: '%s@%s'" %
                    (viewobj.username, viewobj.filename))
            finally:
              mobwrite_core.LOG.debug("text.lock.release on %s", textobj.name)
              textobj.lock.release()

        elif action["mode"] == "delta":
          # It's a delta.
          mobwrite_core.LOG.debug("Got delta: %s@%s",
              viewobj.username, viewobj.filename)
          # mobwrite_core.LOG.debug("Got '%s' delta: '%s@%s'" %
          #     (action["data"], viewobj.username, viewobj.filename))
          if action["server_version"] != viewobj.shadow_server_version:
            # Can't apply a delta on a mismatched shadow version.
            delta_ok = False
            mobwrite_core.LOG.warning("Shadow version mismatch: %d != %d" %
                (action["server_version"], viewobj.shadow_server_version))
          elif action["client_version"] > viewobj.shadow_client_version:
            # Client has a version in the future?
            delta_ok = False
            mobwrite_core.LOG.warning("Future delta: %d > %d" %
                (action["client_version"], viewobj.shadow_client_version))
          elif action["client_version"] < viewobj.shadow_client_version:
            # We've already seen this diff.
            pass
            mobwrite_core.LOG.warning("Repeated delta: %d < %d" %
                (action["client_version"], viewobj.shadow_client_version))
          else:
            # Expand the delta into a diff using the client shadow.
            try:
              diffs = mobwrite_core.DMP.diff_fromDelta(viewobj.shadow, action["data"])
            except ValueError:
              diffs = None
              delta_ok = False
              mobwrite_core.LOG.warning("Delta failure, expected %d length: '%s@%s'" %
                  (len(viewobj.shadow), viewobj.username, viewobj.filename))
            viewobj.shadow_client_version += 1
            if diffs != None:
              if access == Access.ReadOnly:
                output.append("O:" + action["filename"] + "\n")
              else:
                # Textobj lock required for read/patch/write cycle.
                mobwrite_core.LOG.debug("text.lock.acquire on %s", textobj.name)
                textobj.lock.acquire()
                try:
                  self.applyPatches(viewobj, diffs, action)
                finally:
                  mobwrite_core.LOG.debug("text.lock.release on %s", textobj.name)
                  textobj.lock.release()

        # Generate output if this is the last action or the username/filename
        # will change in the next iteration.
        if ((action_index + 1 == len(actions)) or
            actions[action_index + 1]["username"] != viewobj.username or
            actions[action_index + 1]["filename"] != viewobj.filename):
          echo_collaborators = "echo_collaborators" in action
          output.append(self.generateDiffs(viewobj,
                                           last_username, last_filename,
                                           action["echo_username"], action["force"],
                                           delta_ok, echo_collaborators))
          last_username = viewobj.username
          last_filename = viewobj.filename

      finally:
        mobwrite_core.LOG.debug("view.lock.release on %s@%s", viewobj.username, viewobj.filename)
        viewobj.lock.release()

    answer = "".join(output)

    return answer


  def generateDiffs(self, viewobj, last_username, last_filename,
                    echo_username, force, delta_ok, echo_collaborators):
    output = []
    if (echo_username and last_username != viewobj.username):
      output.append("u:%s\n" %  viewobj.username)
    if (last_filename != viewobj.filename or last_username != viewobj.username):
      output.append("F:%d:%s\n" %
          (viewobj.shadow_client_version, viewobj.filename))

    textobj = viewobj.textobj
    mastertext = textobj.text

    if delta_ok:
      if mastertext is None:
        mastertext = ""
      # Create the diff between the view's text and the master text.
      diffs = mobwrite_core.DMP.diff_main(viewobj.shadow, mastertext)
      mobwrite_core.DMP.diff_cleanupEfficiency(diffs)
      text = mobwrite_core.DMP.diff_toDelta(diffs)
      if force:
        # Client sending 'D' means number, no error.
        # Client sending 'R' means number, client error.
        # Both cases involve numbers, so send back an overwrite delta.
        viewobj.edit_stack.append((viewobj.shadow_server_version,
            "D:%d:%s\n" % (viewobj.shadow_server_version, text)))
      else:
        # Client sending 'd' means text, no error.
        # Client sending 'r' means text, client error.
        # Both cases involve text, so send back a merge delta.
        viewobj.edit_stack.append((viewobj.shadow_server_version,
            "d:%d:%s\n" % (viewobj.shadow_server_version, text)))
      viewobj.shadow_server_version += 1
      mobwrite_core.LOG.debug("Sent delta for %s@%s",
          viewobj.username, viewobj.filename)
      # mobwrite_core.LOG.debug("Sent '%s' delta: '%s@%s'" %
      #     (text, viewobj.username, viewobj.filename))
    else:
      # Error; server could not parse client's delta.
      # Send a raw dump of the text.
      viewobj.shadow_client_version += 1
      if mastertext is None:
        mastertext = ""
        viewobj.edit_stack.append((viewobj.shadow_server_version,
            "r:%d:\n" % viewobj.shadow_server_version))
        mobwrite_core.LOG.info("Sent empty raw text: '%s@%s'" %
            (viewobj.username, viewobj.filename))
      else:
        # Force overwrite of client.
        text = mastertext
        text = text.encode("utf-8")
        text = urllib.quote(text, "!~*'();/?:@&=+$,# ")
        viewobj.edit_stack.append((viewobj.shadow_server_version,
            "R:%d:%s\n" % (viewobj.shadow_server_version, text)))
        mobwrite_core.LOG.info("Sent %db raw text: '%s@%s'" %
            (len(text), viewobj.username, viewobj.filename))

    viewobj.shadow = mastertext

    for edit in viewobj.edit_stack:
      output.append(edit[1])

    # Mozilla: We're passing on the first 4 chars of the username here, but
    # it's worth checking if there is still value in doing that
    if echo_collaborators:
      for view in viewobj.textobj.views:
        view.metadata["id"] = view.username[0:4]
        line = "C:" + view.handle + ":" + simplejson.dumps(view.metadata) + "\n"
        output.append(line)

    return "".join(output)


class StreamRequestHandlerDaemonMobWrite(SocketServer.StreamRequestHandler, DaemonMobWrite):
  def __init__(self, a, b, c):
    DaemonMobWrite.__init__(self)
    SocketServer.StreamRequestHandler.__init__(self, a, b, c)

  def feedBuffer(self, name, size, index, datum):
    """Add one block of text to the buffer and return the whole text if the
      buffer is complete.

    Args:
      name: Unique name of buffer object.
      size: Total number of slots in the buffer.
      index: Which slot to insert this text (note that index is 1-based)
      datum: The text to insert.

    Returns:
      String with all the text blocks merged in the correct order.  Or if the
      buffer is not yet complete returns the empty string.
    """
    # Note that 'index' is 1-based.
    if not 0 < index <= size:
      mobwrite_core.LOG.error("Invalid buffer: '%s %d %d'" % (name, size, index))
      text = ""
    elif size == 1 and index == 1:
      # A buffer with one slot?  Pointless.
      text = datum
      mobwrite_core.LOG.debug("Buffer with only one slot: '%s'" % name)
    else:
      # Retrieve the named buffer object.  Create it if it doesn't exist.
      name += "_%d" % size
      # Don't let two simultaneous creations happen, or a deletion during a
      # retrieval.
      mobwrite_core.LOG.debug("lock_buffers.acquire")
      lock_buffers.acquire()
      try:
        if buffers.has_key(name):
          bufferobj = buffers[name]
          bufferobj.lasttime = datetime.datetime.now()
          mobwrite_core.LOG.debug("Found buffer: '%s'" % name)
        else:
          bufferobj = BufferObj(name, size)
          mobwrite_core.LOG.debug("Creating buffer: '%s'" % name)
        mobwrite_core.LOG.debug("buffer.lock.acquire on ??")
        bufferobj.lock.acquire()
        try:
          bufferobj.set(index, datum)
          # Check if Buffer is complete.
          text = bufferobj.get()
        finally:
          mobwrite_core.LOG.debug("buffer.lock.release on ??")
          bufferobj.lock.release()
      finally:
        # Mozilla: This unlock used to come straight after the call to
        # bufferobj.lock.acquire() above.
        # We believe that the order lock-a, lock-b, unlock-a, unlock-b is
        # prone to deadlocks so we've moved 'unlock-a' to here
        mobwrite_core.LOG.debug("lock_buffers.release")
        lock_buffers.release()
      if text == None:
        text = ""
    return urllib.unquote(text)


  def handle(self):
    self.connection.settimeout(TIMEOUT_TELNET)
    if CONNECTION_ORIGIN and self.client_address[0] != CONNECTION_ORIGIN:
      raise("Connection refused from " + self.client_address[0])
    #mobwrite_core.LOG.info("Connection accepted from " + self.client_address[0])

    data = []
    # Read in all the lines.
    while 1:
      try:
        line = self.rfile.readline()
      except:
        # Timeout.
        mobwrite_core.LOG.warning("Timeout on connection")
        break
      data.append(line)
      if not line.rstrip("\r\n"):
        # Terminate and execute on blank line.
        question = "".join(data)
        answer = self.handleRequest(question)
        self.wfile.write(answer)
        break

    # Goodbye
    mobwrite_core.LOG.debug("Disconnecting.")


def kill_views_for_user(username):
  for view in views.values():
    if view.username == username:
      mobwrite_core.LOG.info("kill_views_for_user on %s, %s" % (username, view.filename))
      view.nullify()

def kill_view(username, filename):
  view = fetch_viewobj(username, filename)
  if view is not None:
    mobwrite_core.LOG.info("kill_view on " + username + ", " + filename)
    view.nullify()

def cleanup_thread():
  # Every minute cleanup
  if STORAGE_MODE == BDB:
    import bsddb

  while True:
    cleanup()
    time.sleep(60)


def debugServer():
  mobwrite_core.LOG.info("Views: (count=" + str(len(views)) + ")")
  for key, view in views.items():
    mobwrite_core.LOG.info("- " + str(key) + ": " + str(view))

  mobwrite_core.LOG.info("Texts: (count=" + str(len(texts)) + ")")
  for name, text in texts.items():
    mobwrite_core.LOG.info("- " + name + ": " + str(text))

  mobwrite_core.LOG.info("Buffers: (count=" + str(len(buffers)) + ")")
  for name, buffer in buffers.items():
    mobwrite_core.LOG.info("- " + name + ": " + str(buffer))


# Left at double initial indent to help diff
def cleanup():
    mobwrite_core.LOG.info("Running cleanup task.")
    for view in views.values():
      view.cleanup()
    for text in texts.values():
      text.cleanup()
    for buffer in buffers.values():
      buffer.cleanup()

    # Persist the remaining texts
    for text in texts.values():
      mobwrite_core.LOG.debug("text.lock.acquire on %s", text.name)
      text.lock.acquire()
      try:
        text.save()
      finally:
        mobwrite_core.LOG.debug("text.lock.release on %s", text.name)
        text.lock.release()

    timeout = datetime.datetime.now() - mobwrite_core.TIMEOUT_TEXT
    if STORAGE_MODE == FILE:
      # Delete old files.
      files = glob.glob("%s/*.txt" % DATA_DIR)
      for filename in files:
        if datetime.datetime.fromtimestamp(os.path.getmtime(filename)) < timeout:
          os.unlink(filename)
          mobwrite_core.LOG.info("Deleted file: '%s'" % filename)

    if STORAGE_MODE == BDB:
      # Delete old DB records.
      # Can't delete an entry in a hash while iterating or else order is lost.
      expired = []
      for k, v in lasttime_db.iteritems():
        if datetime.datetime.fromtimestamp(int(v)) < timeout:
          expired.append(k)
      for k in expired:
        if texts_db.has_key(k):
          del texts_db[k]
        if lasttime_db.has_key(k):
          del lasttime_db[k]
        mobwrite_core.LOG.info("Deleted from DB: '%s'" % k)

last_cleanup = time.time()

def maybe_cleanup():
  if PARANOID_SAVE:
    return
  global last_cleanup
  now = time.time()
  if now > last_cleanup + 10:
    cleanup()
    last_cleanup = now


def main():
  if STORAGE_MODE == BDB:
    import bsddb
    global texts_db, lasttime_db
    texts_db = bsddb.hashopen(DATA_DIR + "/texts.db")
    lasttime_db = bsddb.hashopen(DATA_DIR + "/lasttime.db")

  # Start up a thread that does timeouts and cleanup
  thread.start_new_thread(cleanup_thread, ())

  mobwrite_core.LOG.info("Listening on port %d..." % LOCAL_PORT)
  s = SocketServer.ThreadingTCPServer(("", LOCAL_PORT), StreamRequestHandlerDaemonMobWrite)
  try:
    s.serve_forever()
  except KeyboardInterrupt:
    mobwrite_core.LOG.info("Shutting down.")
    s.socket.close()
    if STORAGE_MODE == BDB:
      texts_db.close()
      lasttime_db.close()


from bespin import config

def process_mobwrite(args=None):
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

  config.activate_profile()

  mobwrite_core.logging.basicConfig()
  main()
  mobwrite_core.logging.shutdown()
