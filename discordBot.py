#    This file is part of FalseBot
#    Project Home: https://github.com/FalseAscension/FalseBot
#
#    FalseBot is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    FalseBot is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with FalseBot.  If not, see <https://www.gnu.org/licenses/>.

import json,time,asyncio,aiohttp

apiUrl = "https://discordapp.com/api/"

class opcodes:
    """ 
        Discord Gateway API Opcodes
        See https://discordapp.com/developers/docs/topics/opcodes-and-status-codes#gateway-opcodes 
    """
    DISPATCH                = 0
    HEARTBEAT               = 1
    IDENTIFY                = 2
    STATUS_UPDATE           = 3
    VOICE_STATUS_UPDATE     = 4
    VOICE_SERVER_PING       = 5
    RESUME                  = 6
    RECONNECT               = 7
    REQUEST_GUILD_MEMBERS   = 8
    INVALID_SESSION         = 9
    HELLO                   = 10
    HEARTBEAT_ACK           = 11

class discord_chat_handler:
    """
        A class to be used in conjunction with discord_bot_connection allowing for an easy way
        to bind chat messages to functions.
    
            ch = discord_chat_handler(discord_bot_connection instance, 
                **kwargs { bufferSize : integer,    The size of the buffer to be used for per-channel chat history.
                            }

        Function Definitions:

            register_match()    params: matcher,    A function which should return 'true' if the 
                                                    message matches requirements. See "Matchers" 
                                                    below.
                                        func,       The function to bind match to.
                                        no_self_response,
                                                    Whether or not this function is allowed to 
                                                    respond to itself. Defaults True.

                                Place a function and it's matcher function into the match_registry 
                                tuple.

            match()             params: matcher,    "
                                        kwargs,     keyword args, sometimes containing
                                                    no_self_response (see above).

                                Function decorator to pass a decorated function to register_match().
                                Decorated function will be given a discord message object (https://discordapp.com/developers/docs/resources/channel#message-object)
                                Matcher is given a message object.

            matchContent()
                                See above.

                                For convenience passes the matcher just the message content.

            handle_message_create()
                                params: message,    The message object to be passed by
                                                    discord_bot_connection

                                Bound to discord_bot_connection dispatch registry for event
                                "MESSAGE_CREATE". Finds any matchers which match message
                                contents and execute respective function.

        Matchers:

            A matcher can be any function who returns 'True' when it is passed an appropriate message.

                For example:
                    re.compile('match').match       When this is called with arguments 'match', 
                                                    this should return a MatchObject, eg not None.
                    (lambda x: "foobar" in x)       When this is called with args "foobar" or 
                                                    "barfoobar" (etc) returns True.

                Matchers are passed a discord 'message' object in the form of a dictionary, unless
                created by 'matchContent' in which they are passed the message's content for
                simplicity.

    """
    
    channelBuffer = {}

    def __init__(self, bot_connection, **kwargs):
        bot_connection.register_dispatch('MESSAGE_CREATE',self.handle_message_create)
        self.bot_connection = bot_connection

        if 'bufferSize' in kwargs:
            self.bufferSize = kwargs['bufferSize']
        else:
            self.bufferSize = 3
    
    # Expression registry for matching chat messages. ([MATCHERS],[FUNCTIONS])
    match_registry = ([], [])
    def register_match(self, matcher, func, no_self_respond=True):
        matcher = { "matcher":matcher, "no_self_respond":no_self_respond }

        if matcher in self.match_registry[0]:
            print(f"WARNING: Chat expression {expression} already registered. Re-registering to {func.__name__}")

        self.match_registry[0].append(matcher)
        self.match_registry[1].append(asyncio.coroutine(func))
    
    # Match a message. Will provide a discord message object to decorated functions
    # which match.
    # See https://discordapp.com/developers/docs/resources/channel#message-object
    def match(self, matcher, **kwargs):
        no_self_respond = True
        if 'no_self_respond' in kwargs:
            no_self_respond = kwargs['no_self_respond']

        def decorator(func):
            self.register_match(matcher, func, no_self_respond=no_self_respond)
            return func

        return decorator
    
    # Same as match, however only provides the message content.
    def matchContent(self, matcher, **kwargs):
        return self.match(lambda m: matcher(m['content']), **kwargs)

    async def handle_message_create(self, message):
        
        # If buffering is not disabled, append to the correct channel buffer.
        if self.bufferSize > 0:
            if message['channel_id'] not in self.channelBuffer:
                self.channelBuffer[message['channel_id']] = [None for i in range(self.bufferSize)]

            self.channelBuffer[message['channel_id']].pop(0)
            self.channelBuffer[message['channel_id']].append(message)

        for i,matcher in enumerate(self.match_registry[0]): # Find a matcher whose return value is not 'None' or 'False' and call it's respective function.
            if message['author']['id'] == self.bot_connection.user['id'] and matcher['no_self_respond']: # Don't reply to self unless explicity defined in matcher.
                continue
            if matcher['matcher'](message):
                await self.match_registry[1][i](message)

class discord_bot_connection:
    """
        Main Discord Bot Connection class.

            bot = discord_bot_connection(botToken)

        Function definitions:

            start()             params: None

                                Asyncio start function.
                                Run with asyncio.run(bot.start()
    
            identify()          params: None
            
                                Send an 'IDENTIFY' op code to the websocket with a 'connection 
                                properties' and an 'update status' object, resulting in the
                                Bot coming online.
                                https://discordapp.com/developers/docs/topics/gateway#identify

            heartbeat()         params: heartbeat_interval, interval at which to beat,

                                Sends an OPCODE 1 'HEARTBEAT' payload to the server at the correct
                                interval in order to maintain connection to the websocket.
                                Will throw warning if HEARTBEAT_ACK was not received since last
                                heartbeat.

            handle_message()    params: message,    'message' payload.

                                Deal with incoming websocke messages. Handles incoming messages
                                with opcodes 1-11 and passes opcode 0 'DISPATCH' to function
                                'handle_dispatch'.
                                Calls any user 'message' bindings from the message_registry
                                object,
                                See comment within function for implemented messages.

            handle_dispatch()   params: message     'message' payload.

                                Deal with incoming events. These are the bits that carry the
                                important information. See: 
                                https://discordapp.com/developers/docs/topics/gateway#commands-and-events
                                Currently implemented:
                                    'READY'         -   extract the heartbeat_interval and invoke the
                                                        heartbeat() function
                                    'GUILD_CREATE'  -   store the guild information.
                                Calls any 'dispatch' bindings from the dispatch_registry
                                object,

            api_get_call()      params: path,       relative path for API to be called.
                                        **kwargs    passed to the aiohttp client session.
            
                                Invoke a call to the Discord RESTful API via method GET and return the
                                JSON object.
                                See https://discordapp.com/developers/docs/topics/gateway#get-gateway

            api_post_call()     params: path,       "
                                        **kwargs    passed to the aiohttp client session.

                                Invoke a call to the Discord RESTful API via method POST and return the 
                                JSON object.

            say_in_channel()    params: channel_id,  The ID of the channel for which to send the message
                                        message,    The message to be sent.

                                Send a message to a channel through a Discord RESTful API POST call,
                                Invokes api_post_call().
                                See https://discordapp.com/developers/docs/resources/channel#create-message

            register_message()  params: opcode,     OPCODE for which this function should be bound to.
                                        func,       Function to bind this opcode to.

                                Place a function into the message_registry dict.

            message()           params: opcode,     "
                                
                                Function decorator to pass a decorated function to register_message()

            register_dispatch() params: event,      OPCODE 0 DISPATCH event for which this function
                                                    should be bound to.
                                        func,       Function to bind this event to.

                                Place a function into the dispatch_registry dict.
            
            dispatch()          params: event,      "
                            
                                Function decorator to pass a decorated function to register_dispatch()
    """

    # Some information about the current session
    user = None             # User bot is running under, we will assign this a value later
    private_channels = []   # Private message channels
    guilds = {}             # Guilds bot is a member of. Keyed by ID. Type of 'Guild Object' (https://discordapp.com/developers/docs/resources/guild#guild-object)
    session_id = None       # Current Session ID of the bot. Used for resuming in case of connection loss (not yet implemented).


    APIToken = None

    def __init__(self, botToken, clientID=None, clientSecret=None):
        self.botToken = botToken
        self.clientID = clientID
        self.clientSecret = clientSecret
        self.userAgent = "FalseBot (Python 3.7 AIOHTTP)"
    
    # Register functions to Discord API low-level events.
    dispatch_registry = {}
    def register_dispatch(self, event, func):
        if event in self.dispatch_registry:
            print(f"WARNING: Dispatch event {event} already registered, re-registering to {func.__name__}")
        self.dispatch_registry[event] = func
    
    # @bot.dispatch(event) decorator
    def dispatch(self, event):
        def decorator(func):
            self.register_dispatch(event, func)
            return func
        return decorator 

    # Some bots may also need to know about specific opcodes.
    message_registry = {}
    def register_message(self, opcode, func):
        if opcode in self.message_registry:
            print(f"WARNING: Opcode {opcode} already registered, re-registering to {func.__name__}")
        self.message_registry[opcode] = asyncio.coroutine(func)
    
    # @bot.message(opcode) decorator
    def message(self, opcode):
        def decorator(func):
            self.register_message(opcode, func)
            return func
        return decorator

    # Return the JSON body from a Discord RESTful API GET call.
    async def api_get_call(self, path, url=apiUrl, **kwargs):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}{path}", **kwargs) as response:
                assert 200 == response.status, response.reason
                return await response.json()

    # Same as above with a JSON POST payload.
    async def api_post_call(self, path, **kwargs):
        headers = {
                'Authorization': 'Bot ' + self.botToken,
                'User-Agent': self.userAgent
                }

        if 'json' in kwargs:
            headers['Content-Type'] = 'application/json'

        kwargs['headers'] = headers

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{apiUrl}{path}", **kwargs) as response:
                assert 200 == response.status, response.reason
                return await response.json()
    

    # Send a create message command via the Discord RESTful API.
    async def create_message_async(self, channel_id, **kwargs):
        await self.api_post_call(f"/channels/{channel_id}/messages",
                **kwargs
                )
    
    # Callable without await-ing
    def create_message(self, channel_id, **kwargs):
        asyncio.get_event_loop().create_task(
                self.create_message_async(channel_id, **kwargs)
            )

    def say_in_channel(self, channel_id, message):
        self.create_message(channel_id, data={'content':message})

    def send_file(self, channel_id, filebuf, filename=None, **kwargs):
        form = aiohttp.FormData()
        
        form.add_field('payload_json', json.dumps(kwargs))
        form.add_field('file', filebuf, filename=filename, content_type='application/octet-stream')

        self.create_message(channel_id, data=form)


    # Send a JSON payload to the server.
    async def send_payload(self, op, d, s=None, t=None):
        payload = {"op":op, "d":d, "s":s, "t":t}
        await self.ws.send_json(payload)


    # Heartbeat information
    ack = True
    sequence = None
    
    # Send a heartbeat to the server at the correct interval.
    async def heartbeat(self, interval):
        while True:
            if not self.ack:                # We did not receive a HEARTBEAT_ACK response. Something is wrong!! (Not yet implemented)
                print("Fatal Error: Did not receive HEARTBEAT_ACK. Connection is dead.")
            await self.send_payload(opcodes.HEARTBEAT, self.sequence)
            self.ack = False                # Reset response marker
            await asyncio.sleep(interval / 1000)

    # Handle a 'DISPATCH' event.
    async def handle_dispatch(self, message):
        eventType = message['t']
        event = message['d']

        if eventType == 'READY':
            if self.session_id:
                print("WARNING: Received repeat 'READY' Event although session is already running.")

            self.user = event['user']
            self.session_id = event['session_id']
            for g in event['guilds']:
                self.guilds[g['id']] = g     # Store guild using it's ID as a key.
            print("My username is %s" % self.user['username'])
            print("I am in %i guilds" % len(event['guilds']))

        elif eventType == 'GUILD_CREATE': # Server has made a guild available to us. Store it.
            gid = event['id']
            if not self.guilds[gid]['unavailable']:
                print(f"WARNING: Received repeat GUILD_CREATE event for guild id {gid} ({guild['name']})")
            self.guilds[gid] = event
        
        # Pass off to any function registered for this event by registrar.
        if eventType in self.dispatch_registry:
            await self.dispatch_registry[eventType](event)

    async def handle_message(self, message):
        """
            Called for every message received by websocket connection.
            Message types are defined by 'https://discordapp.com/developers/docs/topics/opcodes-and-status-codes#gateway-opcodes'
            We must process these messages and respond appropriately.

            DISPATCH:           These are the messages which hold the "real" data. we'll hand this off to the dispatch_handler function
                                to keep it clean.
            HEARTBEAT:          Sent every given interval by the server. API documentation doesn't specify what to do, pass.
            RECONNECT:          We must disconnect and reconnect to the gateway for a given reason. Not yet implemented.
            INVALID_SESSION:    Notify us the session ID is invalid. Not yet implemented.
            HELLO:              Received immediately after connecting. Contains crucial heartbeat_interval information.
            HEARTBEAT_ACK:      Must be received in between every heartbeat message we send. Some is wrong if we don't.
        """
        opcode = message['op']

        if opcode == opcodes.DISPATCH:              # Message was a 'DISPATCH' event. Hand it over to the dispatch_handler...
            sequence = message['s']                 # Sequence number used for heartbeat message.
            await self.handle_dispatch(message)

        elif opcode == opcodes.HEARTBEAT:
            pass

        elif opcode == opcodes.RECONNECT:
            pass

        elif opcode == opcodes.INVALID_SESSION:
            pass

        elif opcode == opcodes.HELLO:               # Connection successful. Invoke the heartbeat function
            interval = message['d']['heartbeat_interval']
            print(f"HELLO received, heartbeat_interval set to {interval}")
            asyncio.ensure_future(self.heartbeat(interval))

        elif opcode == opcodes.HEARTBEAT_ACK:       # Mark heartbeat response as received
            self.ack = True

        else:                                       # Unknown opcode.
            print(f"WARNING: Unknown op code {op}")

        # Pass off to any function registered for this opcode by registrar.
        if opcode in self.message_registry:
            await self.message_registry[opcode](message)


    # Send an IDENTIFY payload (https://discordapp.com/developers/docs/topics/gateway#identifying)
    async def identify(self):
        payload = { "token":        self.botToken,
                    "properties":   {
                        "$os":          "linux",
                        "$browser":     "aiohttp",
                        "$device":      "aiohttp"
                        },
                    "compress":     False,
                    "presence":     {
                        "since":        time.time(),
                        "status":       "online",
                        "afk":          False
                        } }
        await self.send_payload(opcodes.IDENTIFY, payload)            

    async def start(self):
        #response = await self.api_post_call("/oauth2/token", params={'grant_type':'client_credentials', 'scope':'identify bot'}, auth=aiohttp.BasicAuth(self.clientID, self.clientSecret))
        #self.APIToken = response['access_token']

        response = await self.api_get_call("/gateway/bot", headers={"Authorization":"Bot " + self.botToken}, url="https://discordapp.com/api/")
        gatewayUrl = response['url']
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"{gatewayUrl}?v=6&encoding=json") as self.ws:
                await self.identify()
                async for msg in self.ws:
                    await self.handle_message(msg.json())

# Main program
async def main():
    bot = discordBot(botToken)
    ws = await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
