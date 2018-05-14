"""StackExchange event handler functions."""

from lrudict import LRUDict
from util import *

class StackHandler(object):
  """Class for handling messages from Stack. Doesn't work on its own; expects to
  be mixed in to something along with an IRCHandler.
  """

  def __init__(self):
    # Recent messages, used to generate the deltas for edits and the thumbnails
    # for replies.
    self._msg_cache = LRUDict(lru_size=256)
    # Messages from me, used for edits.
    self._from_me = {}
    self.stack = None

  def dispatch_stack(self, msg):
    log('<<stack %s', msg)
    try:
      msgtype = msg.__class__.__name__.lower()
      handler = getattr(self, 'stack_' + msgtype, None)
      if handler:
        handler(msg)
      else:
        log('Unrecognized message type from Stack: %s', msgtype)
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
    log("Showing reply to %s", str(msg))

    # Don't have the message being replied to in cache? Bail. Caller will fall
    # back to normal message display.
    replied_to = self._msg_cache.get(msg.parent_message_id, None)
    if not replied_to:
      return False

    # Strip @user from start of original context so we get actual message content.
    context = replied_to.content
    if context.startswith('@'):
      [_,context] = context.split(None, 1)
    context = toplaintext(context, strip_tags=True)

    prefix = ''
    if not msg.content.startswith('@'):
      # Prefix the message with the name of the user being replied to.
      prefix = '@' + replied_to.user.name

    # TODO: configurable context length
    # TODO: configure whether context goes at start or at end
    suffix = ' [re: %s%s]' % (context[0:16], len(context) > 16 and '…' or '')
    self._send_lines(
      tonick(msg.user.name),
      tochannel(msg.room.name),
      toplaintext(prefix + msg.content) + suffix)
    self._msg_cache[msg.data['message_id']] = msg
    return True

  def stack_messageposted(self, msg):
    if msg.user == self.stack.get_me():
      # Save this message so that we can edit it later.
      self._from_me[tochannel(msg.room.name)] = msg.message
      return

    if msg.data['message_id'] in self._msg_cache:
      # We've already seen this message, and it's not an edit (or we would be in
      # stack_messageedited right now instead). Skip.
      log("Discarding message with duplicate id %d", msg.data['message_id'])
      return
    if msg.parent_message_id and msg.show_parent:
      # Message is a reply to an earlier message.
      if self._stack_show_reply(msg):
        return
    self._send_lines(
      tonick(msg.user.name),
      tochannel(msg.room.name),
      toplaintext(msg.content))
    self._msg_cache[msg.data['message_id']] = msg

  def _stack_editmessage(self, channel, find, replace):
    log('Edit request: %s /%s/ => %s', channel, find, replace)
    if channel not in self._from_me:
      return

    msg = self._from_me[channel]
    text = toplaintext(msg.content)
    new_text = re.sub(find, replace, text)
    if new_text != text:
      msg.edit(new_text)

  def stack_messageedited(self, msg):
    if msg.user == self.stack.get_me():
      return

    # msg.content is the new content, and msg.message_id is the ID of the
    # message being edited.
    old_msg = self._msg_cache.get(msg.data['message_id'], None)
    if old_msg:
      log("Cache hit! %s => %s", msg.data['message_id'], old_msg)
      old_txt = toplaintext(old_msg.content)
      new_txt = toplaintext(msg.content)
      text = '* ' + diffstr(old_txt, new_txt, context=8)
    else:
      text = ('* ' + toplaintext(msg.content))
    self._send_lines(tonick(msg.user.name), tochannel(msg.room.name), text)
    self._msg_cache[msg.data['message_id']] = msg

  def stack_userentered(self, msg):
    if msg.user == self.stack.get_me():
      return
    self.to_irc(':%s JOIN %s', tonick(msg.user.name),
      tochannel(msg.room.name))

  def stack_userleft(self, msg):
    self.to_irc(':%s PART %s', tonick(msg.user.name),
      tochannel(msg.room.name))



