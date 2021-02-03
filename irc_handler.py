"""IRC event handling functions."""

import re
import chatexchange.client
import logging

from util import *

#### Event handlers. ####

class IRCHandler(object):
  """Class for handling messages from IRC. Doesn't work on its own; expects to
  be mixed in to something along with a StackHandler.
  """

  def __init__(self):
    self.channels = {}
    self.username = None
    self.password = None
    self.nick = None

  def dispatch_irc(self, line):
    """Parse and dispatch an IRC message.

    The parser does not implement all of RFC1459; it assumes incoming messages are
    always of the form <command> {list args} [:trailing args]

    Returns True if a handler was found and invoked, False otherwise.
    """
    headtail = line.split(' :', 1)
    argv = headtail[0].split()
    if len(headtail) > 1:
      argv += [headtail[1]]

    handler = getattr(self, 'irc_%s' % argv[0].lower(), None)
    if handler:
      handler(*argv[1:])
      return True
    return False


  #### IRC event handlers. ####

  def irc_ping(self, ts):
    self.to_irc(':SEIRC PONG SEIRC :%s', ts)

  def irc_quit(self, reason):
    log("Disconnecting.")
    self.close_when_done()


  #### Authentication handlers.
  # Collects nick, user, and pass, then logs in to StackExchange using the given
  # username and password.

  def irc_nick(self, nick):
    if not self.nick:
      self.nick = nick
      if self.nick and self.username and self.password:
        self.stack_login(self.username, self.password)
    else:
      self.nick = nick

  def irc_pass(self, pwd):
    if not self.password:
      self.password = pwd
      if self.nick and self.username and self.password:
        self.stack_login(self.username, self.password)
    else:
      self.to_irc(':SEIRC 462 :Already registered.')

  def irc_user(self, _nick, _hops, _server, username):
    if not self.username:
      self.username = username
      if self.nick and self.username and self.password:
        self.stack_login(self.username, self.password)
    else:
      self.to_irc(':SEIRC 462 :Already registered.')

  def stack_login(self, username, password):
    log('Logging in to StackExchange as "%s"', username)
    try:
      self.stack = chatexchange.Client(STACK_BACKEND)
      self.stack.login(username, password)
      self.to_irc(':SEIRC 001 %s :Welcome to StackExchange IRC Relay', self.nick)
      self.to_irc(':SEIRC 376 %s :End of MOTD', self.nick)
    except Exception as e:
      logging.exception("Error logging in")
      self.stack = None
      self.to_irc(':SEIRC 464 %s :Login to StackExchange failed: %s', self.nick, e)
      self.to_irc(':%s QUIT', self.nick)
      self.close_when_done()


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
        self.irc_join(channel)
      return
    if chanid.startswith('#') and chanid[1:].isdecimal():
        chanid = chanid[1:]
    if chanid in self.channels or chanid.startswith('#'):
      return

    try:
      channel = self.stack.get_room(chanid)
      channel.join()
      channel.irc_name = tochannel(channel.name)
      self.channels[chanid] = channel
      self.channels[channel.irc_name] = channel
      channel.watch(lambda msg,stack: self.dispatch_stack(msg))
      self.to_irc(':%s JOIN %s', self.nick, channel.irc_name)
      self._send_names(channel)
      self._send_modes(channel)
    except Exception as e:
      logging.exception("Error joining channel")
      self.to_irc(':SEIRC 403 %s :No channel with that ID.', chanid)
      raise

  def irc_names(self, channel):
    if channel in self.channels:
      self._send_names(self.channels[channel])

  def irc_mode(self, channel):
    if channel in self.channels:
      self._send_modes(self.channels[channel])

  def irc_part(self, channel, reason):
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
      log("Not in channel: %s", target)
      log("%s", self.channels.keys())
      self.to_irc(':SEIRC 404 %s :You are not on that channel', self.nick)
      return

    # If the message consists entirely of s/foo/bar/, it's editing the last
    # posted message.
    replace = re.match(r'^s(.)(.*)\1(.*)\1$', msg)
    if replace:
      # FIXME: when we send a (non-edit) message, we should invalidate the
      # previously saved message so we don't apply edits to the wrong thing.
      # We should also record that we have an outbound message on the wire.
      # When we send an edit message, if there is no valid editable message but
      # there is an outbound message, we should save the edit and apply it once
      # the outbound message round-trips.
      return self._stack_editmessage(target, replace.group(2), replace.group(3))

    # If the message starts with a run of non-whitespace followed by :,
    # assume it's being directed at another user and replace the trailing :
    # with a leading @ so that the stack webclient's hilight gets triggered.
    hilight = re.match(r'(\S+): ', msg)
    if hilight and hilight[1] in self.channels[target].get_pingable_user_names():
      msg = re.sub(r'^(\S+): ', r'@\1 ', msg)

    # Translate IRC formatting characters to Slack ones.
    msg = (msg.replace('\x02', '**') # bold
              .replace('\x1F', '_')  # underline -- not supported on stack, map to italics
              .replace('\x1D', '*'))  # italics

    # If the message is a CTCP ACTION, wrap it in * instead.
    msg = re.sub('^\x01ACTION (.*)\x01$', r'*\1*', msg)

    # Send it to Stack.
    self.channels[target].send_message(msg)

