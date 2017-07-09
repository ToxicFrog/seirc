"""StackExchange event handler functions."""

from lrudict import LRUDict
from util import *

class StackHandler(object):
  """Class for handling messages from Stack. Doesn't work on its own; expects to
  be mixed in to something along with an IRCHandler.
  """

  def __init__(self):
    self._msg_cache = LRUDict(lru_size=256)
    self.stack = None

  def dispatch_stack(self, msg):
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
      self.to_irc(':SEIRC NOTICE %s :Error processing message from Stack: %s',
        self.nick, str(e))

  def stack_usermentioned(self, msg):
    # Skip UserMentioned because UserMentioned events are always
    # accompanied by a MessagePosted event with the same payload.
    pass

  def stack_messagereply(self, msg):
    # Same as UserMentioned.
    pass

  def _send_lines(self, src, dst, lines):
    for line in lines.split('\n'):
      if line.strip(" \t\r\n") == '':
        continue
      if (line.startswith('*') and line.endswith('*')
          or line.startswith('\x1F') and line.endswith('\x1F')):
        line = '\x01ACTION ' + line[1:-1] + '\x01'
      self.to_irc(':%s PRIVMSG %s :%s',
        src,
        dst,
        line)

  def _stack_show_reply(self, msg):
    """Given an in-reply-to message, look up the message it's replying to and,
    if found, insert some context into the message.

    Returns True on success, False otherwise.
    """
    replied_to = self._msg_cache.get(msg.parent_message_id, None)
    if not replied_to:
      return False

    # Splice some context in to the start of the message.
    [head,tail] = msg.content.split(None, 1)
    context = toplaintext(replied_to.content)
    if context.startswith('@'):
      [_,context] = context.split(None, 1)
    context = ' [re: %s%s] ' % (context[0:16], len(context) > 16 and '…' or '')
    self._send_lines(
      tonick(msg.user.name),
      tochannel(msg.room.name),
      head + context + toplaintext(tail))
    return True

  def stack_messageposted(self, msg):
    if msg.user == self.stack.get_me():
      # Ignore self-messages
      return
    if msg.parent_message_id:
      # Message is a reply to an earlier message.
      if self._stack_show_reply(msg):
        return
    self._send_lines(
      tonick(msg.user.name),
      tochannel(msg.room.name),
      toplaintext(msg.content))

  def stack_messageedited(self, msg):
    # msg.content is the new content, and msg.message_id is the ID of the
    # message being edited.
    old_msg = self._msg_cache.get(msg.data['message_id'], None)
    if old_msg:
      log("Cache hit! %s => %s" % (msg.data['message_id'], old_msg))
      old_txt = toplaintext(old_msg.content)
      new_txt = toplaintext(msg.content)
      text = '* ' + diffstr(old_txt, new_txt, context=8)
    else:
      text = ('* ' + toplaintext(msg.content))
    self._send_lines(tonick(msg.user.name), tochannel(msg.room.name), text)

  def stack_userentered(self, msg):
    if msg.user == self.stack.get_me():
      return
    self.to_irc(':%s JOIN %s', tonick(msg.user.name),
      tochannel(msg.room.name))

  def stack_userleft(self, msg):
    self.to_irc(':%s PART %s', tonick(msg.user.name),
      tochannel(msg.room.name))



