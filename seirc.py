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

STACK_BACKEND = 'stackexchange.com'
BIND_HOST = 'localhost'
BIND_PORT = 7825

_parser = HTMLParser()


#### Utility functions ####

# Decorator to restrict which IRC messages a given handler fires on, and extract
# arguments from it. TODO: replace this with a basic IRC parser and dispatch based
# on method name in a manner similar to the Stack dispatcher.
def irc(regex):
  regex = re.compile(regex)
  def decorator(f):
    def wrapper(self, line):
      match = regex.match(line)
      if match:
        f(self, *match.groups())
        return True
      else:
        # The command appears to match, or we wouldn't have been called, but the
        # regex doesn't match the actual content of the message.
        # We should probably log an error here.
        return False
    return wrapper
  return decorator


def log(s):
  print(s)

# Convert a Stack user name into an IRC nick
def tonick(user_name):
  return user_name.encode('utf8').decode('raw_unicode_escape').replace(' ', '')
  #.encode('ascii', 'ignore')

# Convert a Stack room name into an IRC channel name
def tochannel(room_name):
  return '#' + room_name.lower().replace(' ', '-')

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
    print('<<irc', msg)
    self.recvq = []
    command = msg.split(None, 1)[0]
    handler = getattr(self, 'irc_' + command.lower(), None)
    if handler:
      if not handler(msg):
        print("Command handler rejected regex for message: %s" % msg)
    else:
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

  #### Handlers for messages coming from IRC ####

  @irc(r'PING (.*)')
  def irc_ping(self, ts):
    self.to_irc(':SEIRC PONG SEIRC :%s', ts)

  @irc(r'NICK (.*)')
  def irc_nick(self, nick):
    self.nick = nick
    if self.nick and self.username and self.password:
      self.login()

  @irc(r'PASS (.*)')
  def irc_pass(self, pwd):
    self.password = pwd
    if self.nick and self.username and self.password:
      self.login()

  @irc(r'USER \S+ \S+ \S+ :(\S+)')
  def irc_user(self, username):
    self.username = username
    if self.nick and self.username and self.password:
      self.login()

  @irc(r'JOIN (\S+)')
  def irc_join(self, chanid):
    if ',' in chanid:
      for channel in chanid.split(','):
        self.irc_join("JOIN %s" % channel)
      return
    if chanid in self.channels:
      return
    if chanid.startswith('#'):
      return
    try:
      channel = self.stack.get_room(chanid)
      channel.join()
      channel.irc_name = tochannel(channel.name)
      self.channels[chanid] = channel
      self.channels[channel.irc_name] = channel
      channel.watch(lambda msg,stack: self._handle_stack(msg))
      self.to_irc(':%s JOIN %s', self.nick, channel.irc_name)
      self._send_names(channel)
      self._send_modes(channel)
    except Exception as e:
      print('ERROR:', e)
      self.to_irc(':SEIRC 403 %s :No channel with that ID.', chanid)

  def _send_modes(self, channel):
    self.to_irc(':SEIRC 324 %s %s +ntr', self.nick, channel.irc_name)

  def _send_names(self, channel):
    self.to_irc(':SEIRC 353 %s = %s :%s', self.nick, channel.irc_name,
        ' '.join([tonick(user.name) for user in channel.get_current_users()]))
    self.to_irc(':SEIRC 366 %s %s :end of NAMES', self.nick, channel.irc_name)

  @irc(r'NAMES (\S+)')
  def irc_names(self, channel):
    if channel in self.channels:
      self._send_names(self.channels[channel])

  @irc(r'MODE (\S+)')
  def irc_mode(self, channel):
    if channel in self.channels:
      self._send_modes(self.channels[channel])

  @irc(r'PART (\S+)')
  def irc_part(self, channel):
    if not channel in self.channels:
      self.to_irc(':SEIRC 442 %s :You are not on that channel', channel)
      return
    channel = self.channels[channel]
    del self.channels[channel.id]
    del self.channels[channel.irc_name]
    channel.leave()

  @irc(r'QUIT ?(.*)')
  def irc_quit(self, reason):
    print("Disconnecting.")
    self.close_when_done()

  @irc(r'PRIVMSG (.*) :(.*)')
  def irc_privmsg(self, target, msg):
    if not target in self.channels:
      self.to_irc(':SEIRC 404 %s :You are not on that channel', self.nick)
      return
    # If the message starts with a run of non-whitespace followed by :,
    # assume it's being directed at another user and replace the trailing :
    # with a leading @ so that the stack webclient's hilight gets triggered.
    msg = re.sub(r'^(\S+): ', r'@\1 ', msg)

    # Translate IRC formatting characters to Slack ones.
    msg = msg.replace('\x02', '*').replace('\x1F', '_')

    # If the message is a CTCP ACTION, wrap it in * instead.
    msg = re.sub('^\x01ACTION (.*)\x01$', r'*\1*', msg)

    # Send it to Stack.
    self.channels[target].send_message(msg)

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
        tonick(msg.user.name),
        tochannel(msg.room.name),
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
    self.to_irc(':%s JOIN %s', tonick(msg.user.name),
      tochannel(msg.room.name))

  def stack_userleft(self, msg):
    self.to_irc(':%s PART %s', tonick(msg.user.name),
      tochannel(msg.room.name))


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
