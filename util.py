"""Assorted utility functions that don't need any additional state."""

import re
import os
import logging

from html.parser import HTMLParser

STACK_BACKEND = 'stackexchange.com'

_parser = HTMLParser()
_logger = logging.getLogger(None)
_logger.setLevel(logging.INFO)
logging.basicConfig()

def log(*s):
  _logger.info(*s)

def tonick(user_name):
  """Convert a Stack user name into an IRC nick name by stripping whitespace.
  Also roundtrips it through raw_unicode_escape to handle nicks in the user
  list (which use embedded \\uXXXX sequences for non-ASCII characters). For
  some reason nicks in MessagePosted events use the actual utf-8 characters,
  which are unharmed by this.
  """
  return (user_name
    .encode('raw_unicode_escape')
    .decode('raw_unicode_escape')
    .replace(' ', ''))

def tochannel(room_name):
  """Convert a Stack room name into an idiomatic IRC channel name by downcasing
  and replacing whitespace with hyphens.
  """
  return '#' + room_name.lower().replace(' ', '-')

def toplaintext(text, strip_tags=False):
  """Convert an HTML message from Stack into a plain text message for IRC."""
  text = (text
    .replace('<b>', '\x02').replace('</b>', '\x02')
    .replace('<u>', '\x1F').replace('</u>', '\x1F')
    .replace('<i>', '\x1F').replace('</i>', '\x1F')
    .replace('<s>', '{').replace('</s>', '}\x02^W\x02')
    .replace('<code>', '`').replace('</code>', '`'))

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

  if strip_tags:
    text = re.sub(r'\s*<[^>]+>', '', text)
  else:
    # Replace <img> and <a> tags with [img ...] and [...]
    text = re.sub(r'\s*<img [^>]*src="([^"]+)"[^>]*>\s*', fix_img, text)
    text = re.sub(r'\s*<a [^>]*href="([^"]+)"[^>]*>\s*', fix_link, text)
    # Replace all other tags with whitespace
    # TODO: deal with cases like '<foo> <bar>' turning into '   ' and not ' '
    text = re.sub(r'(<[^>]+>)+', ' ', text)
    # Replace a leading "@user" reference with "user:"
    text = re.sub(r'^@(\S+)', r'\1:', text)
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


