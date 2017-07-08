# pylint: disable-all

from __future__ import print_function

print("Starting up...")

import asynchat
import asyncore
import os
import re
import socket
import sys

import chatexchange.client
import chatexchange.events

from html.parser import HTMLParser
from lrudict import LRUDict
import libirc

STACK_BACKEND = 'stackexchange.com'
BIND_HOST = 'localhost'
BIND_PORT = 7825

_parser = HTMLParser()

# TODO: import chatexchange.browser and patch RoomPollingWatcher._runner()
# and RoomSocketWatcher._runner() to catch and handle exceptions from the HTTP
# layer.


#### Utility functions ####

def log(s):
  print(s)


# Convert HTML-bearing messages from Stack into plain text suitable for IRC.
def toplaintext(text):
  text = (text
    .replace('<b>', '\x02')
    .replace('</b>', '\x02')
    .replace('<u>', '\x1F')
    .replace('</u>', '\x1F')
    .replace('<i>', '\x1F')
    .replace('</i>', '\x1F')
    .replace('<code>', '`')
    .replace('</code>', '`')
    )

  # If we see the same link multiple times in a message, we only convert the
  # first one for brevity's sake.
  seen_links = set()

  def fix_img(match):
    return fix_link(match).replace('[', '[img ', 1)

  def fix_link(match):
    link = match.group(1)
    if link in seen_links:
      return ''
    seen_links.add(link)
    if link.startswith('//'):
      return ' [http:' + link + '] '
    if link.startswith('/'):
      return ' [http://' + STACK_BACKEND + link + '] '
    return ' [' + link + '] '

  text = re.sub(r'\s*<img [^>]*src="([^"]+)"[^>]*>\s*', fix_img, text)
  text = re.sub(r'\s*<a [^>]*href="([^"]+)"[^>]*>\s*', fix_link, text)
  text = re.sub(r'(<[^>]+>)+', ' ', text)
  return _parser.unescape(text)

def diffstr(old, new, context=0):
  """Return only the part of `new` that is different from `old`, by stripping
  the common prefix and suffix (if any) from them."""
  prefix = '…'
  suffix = '…'
  prefix_len = max(0, len(os.path.commonprefix([old, new])) - context)
  suffix_len = -max(0, len(os.path.commonprefix([old[::-1], new[::-1]])) - context)
  if prefix_len == 0:
    prefix = ''
  if suffix_len == 0:
    suffix_len = None
    suffix = ''
  return prefix + new[prefix_len:suffix_len] + suffix


#### Server code ####

class IRCUser(asynchat.async_chat):
  """Represents a single connected user.

  This class is responsible for handling incoming traffic from IRC, and either
  generating the correct replies or sending the corresponding messages to Slack
  (or both).
  """
  handlers = []
  def __init__(self, sock):
    asynchat.async_chat.__init__(self, sock=sock)
    self.recvq = []
    self.channels = {}
    self.set_terminator(b'\r\n')
    # IRC user state
    self.username = None
    self.password = None
    self.nick = None
    self.stack = None

  def collect_incoming_data(self, data):
    self.recvq.append(data.decode('utf8', 'replace'))

  def found_terminator(self):
    """Called when we've read an entire line from IRC."""
    msg = ''.join(self.recvq)
    self.recvq = []

    print('<<irc', msg)
    if not libirc.dispatch(self, msg):
      # Unrecognized commands from IRC get ignored.
      print("Unknown command from IRC: %s" % msg)

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
    print("irc>>", (fmt % tuple(args)))
    self.push((fmt % tuple(args) + '\r\n').encode('utf-8'))

  def login(self):
    print('Logging in to StackExchange as', self.username)
    try:
      self.stack = chatexchange.Client(STACK_BACKEND)
      self.stack.login(self.username, self.password)
      self.to_irc(':SEIRC 001 %s :Welcome to StackExchange IRC Relay', self.nick)
      self.to_irc(':SEIRC 376 %s :End of MOTD', self.nick)
    except Exception as e:
      print('ERROR:', e)
      self.stack = None
      self.to_irc(':SEIRC 464 %s :Login to StackExchange failed: %s', self.nick, e)
      self.to_irc(':%s QUIT', self.nick)
      self.close_when_done()

  #### Handlers for messages from Stack ####

  _msg_cache = LRUDict(lru_size=256)

  def _handle_stack(self, msg):
    print('<<stack', msg)
    try:
      msgtype = msg.__class__.__name__.lower()
      handler = getattr(self, 'stack_' + msgtype, None)
      if handler:
        handler(msg)
        if 'message_id' in msg.data:
          self._msg_cache[msg.data['message_id']] = msg
      else:
        print('Unrecognized message type from Stack: %s' % msgtype)
    except Exception as e:
      print('!! Error handling message from Stack: %s' % str(e))

  def stack_usermentioned(self, msg):
    # Skip UserMentioned because UserMentioned events are always
    # accompanied by a MessagePosted event with the same payload.
    pass

  def stack_messageposted(self, msg):
    if msg.user == self.stack.get_me():
      # Ignore self-messages
      return
    for line in toplaintext(msg.content).split('\n'):
      line = line.strip(" \t\r\n")
      if line == '':
        continue
      if (line.startswith('*') and line.endswith('*')
          or line.startswith('\x1F') and line.endswith('\x1F')):
        line = '\x01ACTION ' + line[1:-1] + '\x01'
      self.to_irc(':%s PRIVMSG %s :%s',
        libirc.tonick(msg.user.name),
        libirc.tochannel(msg.room.name),
        line)

  def stack_messageedited(self, msg):
    # msg.content is the new content, and msg.message_id is the ID of the
    # message being edited.
    if msg.data['message_id'] in self._msg_cache:
      log("Cache hit! %s => %s" % (msg.data['message_id'], msg))
      msg.content = '* ' + diffstr(
        self._msg_cache[msg.data['message_id']].content,
        msg.content, context=8)
    else:
      msg.content = '* ' + msg.content
    self.stack_messageposted(msg)

  def stack_userentered(self, msg):
    if msg.user == self.stack.get_me():
      return
    self.to_irc(':%s JOIN %s', libirc.tonick(msg.user.name),
      libirc.tochannel(msg.room.name))

  def stack_userleft(self, msg):
    self.to_irc(':%s PART %s', libirc.tonick(msg.user.name),
      libirc.tochannel(msg.room.name))


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
        print("New connection from %s" % str(client_info))
        IRCUser(sock=client_info[0])

    def handle_close(self):
        self.close()

listener = IRCServer(address=(BIND_HOST, BIND_PORT))
print("Listening on", BIND_PORT)
asyncore.loop()
