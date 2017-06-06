# SEIRC -- a Stack Exchange Chat <-> IRC proxy

SEIRC is a simple proxy, written in python, that translates between IRC traffic
to an IRC client, and HTTP traffic to the Stack Exchange Chat servers. This means
you can connect to, and chat on, any Stack Exchange chatroom using your IRC client.
It does not act as a bot, passing messages back and forth between IRC and Stack;
there's no need for a separate IRC server. Rather, it logs into Stack *as you*
and then pretends to be an IRC server for the convenience of your client.

## Limitations

This is something I hacked together in an afternoon. There are probably lots of
things it doesn't support, or supports badly. But the basics of chatting and
receiving chat messages work.

It doesn't display backscroll from previous chatting in the channel.

It also doesn't have any sort of configuration knobs or command line flags, yet.

Also, it currently echoes all traffic it receives to stdout, *including your password*.
Don't use this anywhere someone malicious could read its output.

## Prerequisites

- Python 2.7
- ChatExchange 0.0.3 (installable via pip)
- A StackExchange account *with a password*

### Adding a password to your SE account

If you habitually log in to SE using another authentication provider, like Google
or Steam, your SE account may not have a password. In that case, here's how to add
a password:

- Log out of SE
- Go to the SE login screen
- Click 'forgot password'
- Enter the email you registered with
- Wait for the email telling you that your SE account doesn't have a password
  set to arrive
- Click the link in the email and set a password

## Running the proxy

Just `python seirc.py`. It should start up and tell you what port it's listening
on.

If you want to change the settings (connect to a different chat backend, listen
on a different port or interface), right now you have to do that by editing those
settings in `seirc.py`; they're right under all the `import`s.

## Connecting to it

Configure your IRC client as follows:

- server: `localhost:7825` (unless you changed those settings)
- nick: whatever you want
- username: your Stack Exchange account email
- password: your Stack Exchange account

And then connect. The proxy will use your IRC username and password to log in to
Stack, and your nick for the name it displays for you in IRC. (Users in Stack will
see whatever your configured display name is there.)

### Joining channels

At the moment, you can't join channels by name; the Stack client library doesn't
have any way to look up a channel by name, only by ID. (This may not be possible
in general; Stack channels aren't guaranteed to have unique names, nor to keep one
name for their lifetime).

To figure out what the ID of a channel is, visit it in your browser; the URL
will be something like `http://chat.stackexchange.com/rooms/<number>/<name>`.
The `<number>` is the room ID. `/join` that from IRC and away you go. The proxy
will look up the channel and create a corresponding IRC channel with an appropriate
name.

For example, to join Sandbox, you'd see that the URL is
`http://chat.stackexchange.com/rooms/1/sandbox`, type `/join 1` in IRC, and
find yourself in `#sandbox` on IRC a moment later.

### Chatting

- *Stack names* are translated into IRC-style nicks without whitespace.
- *Edits* show up as the edited line, repeated, with a `*` in front
- *@ hilights* work properly. Starting a line with `Name: ` (as is common with
  tab completion in most IRC clients) will automatically be translated to
  `@Name `.
- *Links and inline images* are displayed wrapped in [].
- *Multi-line messages* show up as multiple IRC messages.

## TODO

- Edits should show only the diff, not the entire line
- `*` and `_` render as italic in SE, but not in IRC
- IRC formatting characters sometimes don't get passed to SE properly
- Channel topic
- Replies should include the timestamp of the message being replied to, if it's still in the cache
