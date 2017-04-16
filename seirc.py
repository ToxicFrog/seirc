import asynchat
# import socket
# import sys
import re

# import chatexchange.client
# import chatexchange.events

STACK_BACKEND = 'stackexchange.com'


def irc(regex):
  regex = re.compile(regex)
  def decorator(f):
    def wrapper(self, line):
      match = regex.match(line)
      if match:
        return f(self, *match.groups())
      else:
        # The command appears to match, or we wouldn't have been called, but the
        # regex doesn't match the actual content of the message.
        # We should probably log an error here.
        pass
    return wrapper
  return decorator


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
    self.set_terminator('\n')

  def collect_incoming_data(self, data):
    self.recvq.append(data)

  def found_terminator(self):
    """Called when we've read an entire line from IRC."""
    msg = ''.join(self.recvq)
    self.recvq = []
    command = msg.split(None, 1)[0]
    handler = getattr(self, 'irc_' + command.lower())
    if handler:
      handler(msg)
    else:
      # Unrecognized commands from IRC get ignored.
      pass

  @irc(r'NICK (.*)')
  def irc_nick(self, nick):
    self.push('>> nick ' + nick + '\n')
    # client = chatexchange.client.Client(host_id)
    # client.login(email, password)
    pass

  @irc(r'PASS (.*)')
  def irc_pass(self, pwd):
    self.push('>> pass ' + pwd + '\n')
    pass

import asyncore
import logging
import socket

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
        IRCUser(sock=client_info[0])

    def handle_close(self):
        self.close()

listener = IRCServer(address=('0.0.0.0', 9996))
asyncore.loop()

# room_id = raw_input("Stack Exchange room id: ")
# email = raw_input("Stack Exchange bot email: ")
# password = raw_input("Stack Exchange bot password: ")

# #Based on code from http://stackoverflow.com/a/12219119/1172541

# irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #defines the socket
# print "connecting to:"+server
# irc.connect((server, 6667))                                                         #connects to the server
# irc.send("USER "+ botnick +" "+ botnick +" "+ botnick +" :StackExchange IRC Relay\n") #user authentication
# irc.send("NICK "+ botnick +"\n")                            #sets nick
# # irc.send("PRIVMSG nickserv :iNOOPE\r\n")    #auth

# #Based on sample from https://github.com/Manishearth/ChatExchange/blob/master/examples/chat.py

# def on_message(message, client):
#     if not isinstance(message, chatexchange.events.MessagePosted):
#         # Ignore non-message_posted events.
#         return
#     if message.user == client.get_me():
#         # Ignore messages from self
#         return
#     print "<<",message.user.name,message.content
#     irc.send("PRIVMSG " + channel + ' :<' + message.user.name + '> ' + message.content + '\r\n')

# host_id = 'stackexchange.com'
# print "connecting to:"+host_id
# client = chatexchange.client.Client(host_id)
# client.login(email, password)

# room = client.get_room(room_id)
# room.join()
# room.watch(on_message)

# def parseIRC(text):
#     components = text.split(':',2)
#     name = components[1].split('!')[0]
#     if "JOIN" in components[1]:
#         return name + " joined."
#     message = components[2]
#     return "<"+name+"> "+message

# # Also from http://stackoverflow.com/a/12219119/1172541

# text=irc.recv(2048)  #receive the text
# irc.send("JOIN "+ channel +"\n")        #join the chan
# while True:    #puts it in a loop
#     if 'PING' in text:                          #check if 'PING' is found
#         irc.send('PONG ' + text.split() [1] + '\r\n') #returnes 'PONG' back to the server (prevents pinging out!)

#     try:
#         print ">>", text
#         room.send_message(parseIRC(text))
#     except IndexError: pass
#     text=irc.recv(2048)  #receive the text
