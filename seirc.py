# pylint: disable-all

from __future__ import print_function

from util import *

log("Starting up...")

import asynchat
import asyncore
import socket
import sys
import os

import chatexchange.client
import chatexchange.events

from stack_handler import StackHandler
from irc_handler import IRCHandler

BIND_HOST = 'localhost'
BIND_PORT = 7825

# TODO: import chatexchange.browser and patch RoomPollingWatcher._runner()
# and RoomSocketWatcher._runner() to catch and handle exceptions from the HTTP
# layer.

#### HACK HACK HACK ####
# Patch chatexchange.browser.Browser to turn unhandled exceptions into program
# exit.
# Really we should just disconnect the client or something here, but for now I
# just want something that will cause the client to reconnect with a minimum
# of fuss.
from chatexchange.browser import Browser

def exceptionToExit(fn):
  def wrapped(*args, **kwargs):
    try:
      return fn(*args, **kwargs)
    except Exception as e:
      log("Unhandled exception: %s", e)
      log('Exiting...')
      os._exit(1)
  return wrapped

Browser._request = exceptionToExit(Browser._request)
log("Patched Browser.")

#### Server code ####

class IRCUser(asynchat.async_chat, IRCHandler, StackHandler):
  """Represents a single connected user.

  This class is responsible for handling incoming traffic from IRC, and either
  generating the correct replies or sending the corresponding messages to Slack
  (or both).
  """
  handlers = []
  def __init__(self, sock):
    asynchat.async_chat.__init__(self, sock=sock)
    IRCHandler.__init__(self)
    StackHandler.__init__(self)

    self.recvq = []
    self.set_terminator(b'\r\n')

  def collect_incoming_data(self, data):
    self.recvq.append(data.decode('utf8', 'replace'))

  def found_terminator(self):
    """Called when we've read an entire line from IRC."""
    msg = ''.join(self.recvq)
    self.recvq = []

    log('<<irc %s', msg)
    if not self.dispatch_irc(msg):
      # Unrecognized commands from IRC get ignored.
      log("Unknown command from IRC: %s" % msg)

  def handle_close(self):
    if self.stack and self.stack.logged_in:
      self.stack.logout()
    self.close()
    sys.exit(0)

  def handle_error(self):
    try:
      self.stack.logout()
    except:
      pass
    self.to_irc(':%s QUIT :Connection to Stack lost', self.nick)
    self.close_when_done()
    return asynchat.async_chat.handle_error(self)

  def to_irc(self, fmt, *args):
    log("irc> %s", (fmt % tuple(args)))
    self.push((fmt % tuple(args) + '\r\n').encode('utf-8'))


class IRCServer(asyncore.dispatcher):
    """Receives connections and establishes handlers for each client.
    """

    def __init__(self, address):
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.bind(address)
        self.address = self.socket.getsockname()
        self.listen(1)

    def handle_accept(self):
        # Called when a client connects to our socket
        client_info = self.accept()
        log("New connection from %s" % str(client_info))
        IRCUser(sock=client_info[0])

    def handle_close(self):
        self.close()


listener = IRCServer(address=(BIND_HOST, BIND_PORT))
log("Listening on", BIND_PORT)
asyncore.loop()
