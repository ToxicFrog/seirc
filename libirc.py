"""IRC event handling functions.

All event handling functions are named as `irc_<event>` and take a reference to
an IRC/Stack connection mediator as their first argument.

Also exports `dispatch(self, line)` which takes a raw line from IRC, parses it,
and invokes the appropriate event handler.
"""

import sys
__module__ = sys.modules[__name__]


def dispatch(self, line):
  """Parse and dispatch an IRC message.

  The parser does not implement all of RFC1459; it assumes incoming messages are
  always of the form <command> {list args} [:trailing args]

  Returns True if a handler was found and invoked, False otherwise.
  """
  headtail = line.split(' :', 1)
  argv = headtail[0].split()
  if len(headtail) > 1:
    argv += [headtail[1]]

  handler = getattr(__module__, 'irc_%s' % argv[0].lower(), None)
  if handler:
    handler(self, *argv[1:])
    return True
  return False


#### Public utility functions. ####

def tonick(user_name):
  """Convert a Stack user name (with embedded unicode escapes and possibly
  whitespace) into an IRC nick (with no whitespace and UTF-8 encoding).
  """
  return user_name.encode('utf8').decode('raw_unicode_escape').replace(' ', '')

def tochannel(room_name):
  """Convert a Stack room name into an idiomatic IRC channel name by downcasing
  and replacing whitespace with hyphens.
  """
  return '#' + room_name.lower().replace(' ', '-')


#### IRC event handlers. ####

def irc_ping(self, ts):
  self.to_irc(':SEIRC PONG SEIRC :%s', ts)

def irc_quit(self, reason):
  print("Disconnecting.")
  self.close_when_done()


#### Authentication handlers.
# Collects nick, user, and pass, then logs in to StackExchange using the given
# username and password.

def irc_nick(self, nick):
  if not self.nick:
    self.nick = nick
    if self.nick and self.username and self.password:
      self.login()
  else:
    self.nick = nick

def irc_pass(self, pwd):
  if not self.password:
    self.password = pwd
    if self.nick and self.username and self.password:
      self.login()
  else:
    self.to_irc(':SEIRC 462 :Already registered.')

def irc_user(self, _nick, _hops, _server, username):
  if not self.username:
    self.username = username
    if self.nick and self.username and self.password:
      self.login()
  else:
    self.to_irc(':SEIRC 462 :Already registered.')


#### Channel management. ####

def _send_modes(self, channel):
  self.to_irc(':SEIRC 324 %s %s +ntr', self.nick, channel.irc_name)

# FIXME: if this results in too many names, split across multiple messages.
def _send_names(self, channel):
  self.to_irc(':SEIRC 353 %s = %s :%s', self.nick, channel.irc_name,
      ' '.join([tonick(user.name) for user in channel.get_current_users()]))
  self.to_irc(':SEIRC 366 %s %s :end of NAMES', self.nick, channel.irc_name)

def irc_join(self, chanid):
  """Join a channel, or comma-separated list of channels.

  We don't currently have a way to look up channels by name, so attempts to join
  #-prefixed IRC channels are currently ignored. To join a StackExchange channel,
  use the SE numeric channel ID, e.g. /join 1,35 to join Sandbox and The Bridge.
  """
  if ',' in chanid:
    for channel in chanid.split(','):
      irc_join(self, channel)
    return
  if chanid in self.channels or chanid.startswith('#'):
    return

  try:
    channel = self.stack.get_room(chanid)
    channel.join()
    channel.irc_name = tochannel(channel.name)
    self.channels[chanid] = channel
    self.channels[channel.irc_name] = channel
    channel.watch(lambda msg,stack: self._handle_stack(msg))
    self.to_irc(':%s JOIN %s', self.nick, channel.irc_name)
    _send_names(self, channel)
    _send_modes(self, channel)
  except Exception as e:
    print('ERROR:', e)
    self.to_irc(':SEIRC 403 %s :No channel with that ID.', chanid)

def irc_names(self, channel):
  if channel in self.channels:
    _send_names(self, self.channels[channel])

def irc_mode(self, channel):
  if channel in self.channels:
    _send_modes(self, self.channels[channel])

def irc_part(self, channel):
  """Leave a channel. Accepts both IRC channel names and SE channel IDs."""
  if not channel in self.channels:
    self.to_irc(':SEIRC 442 %s :You are not on that channel', channel)
    return
  channel = self.channels[channel]
  del self.channels[channel.id]
  del self.channels[channel.irc_name]
  channel.leave()


#### Messages. ####

# TODO: implement support for per-message replies.

def irc_privmsg(self, target, msg):
  """Send a message to a channel. Note: Stack does not support PMs."""

  if not target in self.channels:
    # DEBUG: sometimes we end up still receiving events from a channel but not
    # in the channel according to IRC.
    print("Not in channel: %s", target)
    print(self.channels.keys())
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

