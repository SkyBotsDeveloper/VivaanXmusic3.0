HELP_1_PROMO = """
<b><u>Promotion / Demotion</u></b>

- /promote [reply/@user/id] - grant limited admin rights.
- /fullpromote [reply/@user/id] - grant full admin rights.
- /demote [reply/@user/id] - remove admin rights.
- /tempadmin [reply/@user/id] [time] - grant temporary admin rights.
"""

HELP_1_PUNISH = """
<b><u>Punishment / Policing</u></b>

- /ban [reply/@user/id] - ban a user from the group.
- /unban [reply/@user/id] - unban a user.
- /kick [reply/@user/id] - kick a user.
- /kickme - leave the group yourself.
- /mute [reply/@user/id] - mute a user.
- /tmute [reply/@user/id] [time] - mute for a limited time.
- /unmute [reply/@user/id] - unmute a user.
- /tban [reply/@user/id] [time] - ban for a limited time.
- /sban [reply/@user/id] - silent ban.
- /dban [reply only] - delete the replied message and ban the sender.
"""

HELP_2 = """
<b><u>Admin Control</u></b>
Core in-call controls for group admins. Linked-channel variants use the same command with a <code>c</code> prefix where available.

- /pause, /cpause - pause the current stream.
- /resume, /cresume - resume the paused stream.
- /skip, /cskip, /next, /cnext - skip the current track.
- /end - stop playback and clear the queue.
- /player, /cplayer, /playing, /cplaying - open the player or view now playing info.
- /queue, /cqueue - show queued tracks.
- /reload, /refresh, /admincache - rebuild admin cache.
- /reboot - reset the assistant and current VC session for this chat.
"""

HELP_3 = """
<b><u>Auth Users</u></b>

- /auth [reply/@user/id] - authorize a user for admin play controls.
- /unauth [reply/@user/id] - remove an authorized user.
- /authlist, /authusers - list authorized users in the chat.
"""

HELP_4 = """
<b><u>Blacklist Chat</u></b> <i>(sudo)</i>

- /blchat, /blacklistchat [chat id] - blacklist a chat from using the bot.
- /whitelistchat, /unblacklistchat, /unblchat [chat id] - remove a blacklisted chat.
- /blchats, /blacklistedchats - list blacklisted chats.
"""

HELP_5 = """
<b><u>Block Users</u></b> <i>(sudo)</i>

- /block [reply/@user/id] - block a user from using the bot.
- /unblock [reply/@user/id] - unblock a user.
- /blocked, /blockedusers, /blusers - list blocked users.
"""

HELP_6 = """
<b><u>Channel Play</u></b>
Use these when a linked channel is attached to a group.

- /channelplay [chat username/id] or /channelplay disable - link or unlink a channel.
- /cplay, /cvplay - play audio or video in linked-channel mode.
- /cplayforce, /cvplayforce - force-play in linked-channel mode.
- /cqueue, /cplayer, /cplaying - inspect the linked-channel queue or player.
"""

HELP_7 = """
<b><u>Extra Tools</u></b>

- /tgm, /tgt, /telegraph - upload replied media to Telegraph.
- /tr - translate text or a replied message.
- /short, /unshort - shorten or expand a URL.
- /speedtest, /spt - run a network speed test.
- /webdl [url] - download a website snapshot/archive.
- /bug [text or reply] - send a bug report to the owner.
"""

HELP_8 = """
<b><u>Global Ban</u></b> <i>(sudo)</i>

- /gban, /globalban [reply/@user/id] - globally ban a user across served chats.
- /ungban [reply/@user/id] - remove a global ban.
- /gbannedusers, /gbanlist - list globally banned users.
"""

HELP_9 = """
<b><u>Global Cast</u></b> <i>(sudo)</i>

- /broadcast [text or reply] - broadcast a message to users/chats served by the bot.
"""

HELP_10 = """
<b><u>Games</u></b>

- /dice, /dart, /basket, /jackpot, /ball, /football - Telegram dice games.
- /truth - get a random truth question.
- /dare - get a random dare.
"""

HELP_11 = """
<b><u>AI Chat</u></b>

- jarvis [prompt] - chat with the assistant using the jarvis trigger.
- assis [prompt] - get an AI voice reply.
- /gpt, /claude, /bard, /gemini, /llama, /mistral - text AI replies.
- /geminivision - analyze a replied image.
- /chatgpt, /ai, /ask, /Master - alternate text-AI entry commands.
"""

HELP_12 = """
<b><u>Info</u></b>

- /id - get chat, user, or replied-message IDs.
- /info, /userinfo, /whois - inspect a user's details.
- /sg - fetch user history details.
- /groupdata - show current group information.
- /phone - look up details for a phone number.
"""

HELP_13 = """
<b><u>Image</u></b>

- /editimg - AI edit a replied image or image album with a prompt.
- /getdraw - generate an AI image from a prompt.
- /upscale - upscale a replied image.
- /rmbg - remove the background from a replied image.
- /waifu [tag] - fetch a waifu image by tag.
"""

HELP_14 = """
<b><u>Log / Maintenance</u></b> <i>(sudo)</i>

- /logger [enable|disable] - toggle live logging.
- /maintenance [enable|disable] - toggle maintenance mode.
- /logs, /getlog, /getlogs - fetch current logs.
- /update, /gitpull - pull latest upstream changes.
- /restart - restart the bot process.
"""

HELP_15 = """
<b><u>Loop</u></b>

- /loop [enable|disable|count] - repeat the current track.
- /cloop [enable|disable|count] - same action for linked-channel playback.
"""

HELP_16 = """
<b><u>Group Management</u></b>

- /pin, /unpin - pin or unpin messages.
- /settitle - change the group title.
- /setdiscription - change the group description.
- /setphoto, /removephoto - set or remove the group photo.
- /welcome [on|off] - toggle welcome messages.
- /admins, /staff - list admins in the group.
- /bots - list bot accounts in the group.
- /zombies - clean deleted accounts from the group.
- /imposter [on|off] - toggle the username/name change watcher.
- /lang, /setlang, /language - change bot language for the chat.
- /givelink - export the current group's invite link.
- /user - export the member list as CSV or TXT.
"""

HELP_17 = """
<b><u>Masti / Fun</u></b>

- /couple, /love, /wish, /cute, /bored - fun social commands.
- /cutie, /horny, /hot, /sexy, /sad, /lesbian, /chill, /kill - percentage-style fun ratings.
- Reaction GIFs: /hug, /kiss, /slap, /punch, /bite, /pat, /cuddle, /tickle, /poke, /wave, /highfive, /dance, /smile, /blush, /smug, /wink, /stare, /shrug, /happy, /baka, /feed, /nom, /yawn, /facepalm, /yeet, /think, /shoot, /peck, /nod, /nope, /sleep, /lurk.
"""

HELP_18 = """
<b><u>Mass Actions</u></b>
Use with care.

- /deleteall - purge all messages in the current group after confirmation.
- /purge, /spurge - bulk delete from a replied message up to the current message.
- /del - delete a replied message quickly.
"""

HELP_19 = """
<b><u>Ping / Stats</u></b>

- /start - start the bot in private.
- /help - open the help menu.
- /ping - show bot latency and runtime info.
- /stats, /gstats - show bot statistics.
"""

HELP_20 = """
<b><u>Play</u></b>

- /play, /vplay - play audio or video by query, URL, or replied media.
- /playforce, /vplayforce - force-start a new track immediately.
- /autoplay, /cautoplay [on|off] - continue with similar songs when the queue ends.
- /settings, /setting - open group playback settings.
- /playmode, /mode - switch direct/inline play mode.
"""

HELP_21 = """
<b><u>Repo Info</u></b>

- /repo - open repo/support buttons.
- /pypi [package] - fetch package info from PyPI.
- /downloadrepo [github url] - download a repository as a zip.
"""

HELP_22 = """
<b><u>Search</u></b>

- /anime [query] - search anime details.
- /movie [query] - fetch movie information.
- /news [topic] - show the latest headlines on a topic from reliable sources.
- /domain [name] - inspect a domain.
- /ip [address] - inspect IP information.
- /mongochk [mongo url] - check a MongoDB URI.
- /weather [location] - show weather for a place.
- /population [country code] - fetch population info for a country.
"""

HELP_23 = """
<b><u>Seek</u></b>

- /seek, /cseek [seconds] - jump forward in the current stream.
- /seekback, /cseekback [seconds] - jump backward in the current stream.
"""

HELP_24 = """
<b><u>Shuffle</u></b>

- /shuffle, /cshuffle - shuffle the queue.
- /queue, /cqueue - inspect the queue after shuffling.
"""

HELP_25 = """
<b><u>Download</u></b>

- /song [title/url] - download a song from YouTube.
- /lyrics [title or lyric line] - search matching songs, then fetch full lyrics by button.
- /insta, /ig [instagram url] - download Instagram media.
- /youtube, /yt [youtube url] - download YouTube media with audio.
- /facebook, /fb [facebook url] - download Facebook media.
- /x, /twitter [post url] - download X/Twitter post media.
- /snap, /snapchat [snapchat url] - download Snapchat media.
- /tiktok, /tt [tiktok url] - download TikTok media.
- /remove [audio|video] - remove audio or video from a replied media file.
"""

HELP_26 = """
<b><u>Speed</u></b>

- /speed, /slow, /playback [value] - change playback speed.
- /cspeed, /cslow, /cplayback [value] - same controls for linked-channel playback.
"""

HELP_27 = """
<b><u>Sticker</u></b>

- /mmf - turn replied media into a meme-style sticker.
- /tiny - shrink a replied sticker.
- /kang - steal a replied sticker/image into your pack.
- /packkang - clone a full sticker pack item by item.
- /stickerid, /stid - show sticker IDs for a replied sticker.
- /st - send a sticker by its file ID.
- /stdl - download a replied sticker.
- /meme - generate a meme image.
"""

HELP_28 = """
<b><u>Tag-All</u></b>

- /utag, /all, /mention [text] - mention everyone with custom text or a replied message.
- /cancel, /ustop - stop utag mention spam.
- /tagall - random funny tag-all mode.
- /tagoff, /tagstop - stop random tag-all mode.
- /gmtag, /gmstop - morning wish tag mode and stop.
- /gntag, /gnstop - night wish tag mode and stop.
- /hitag, /histop - Hindi quote tag mode and stop.
- /lifetag, /lifestop - English quote tag mode and stop.
- /shayari, /shayarioff - shayari tag mode and stop.
"""

HELP_29 = """
<b><u>Text Editing</u></b>

- /font, /fonts - stylize text with font buttons.
- /figlet - generate figlet-style text.
- /encode, /decode - convert text to and from hex.
- /genpassword, /genpw - generate a password.
- /write - render text in notebook style.
- /day - convert a date to its weekday.
- /qr - generate a QR code.
- /q - create a quote sticker from replied messages.
"""

HELP_30 = """
<b><u>Gen Vid</u></b>

- /genvid [prompt] - generate a short AI video from text.
- Reply to an image with /genvid [motion prompt] - animate that image.
- The bot automatically retries across the configured video backends.
"""

HELP_31 = """
<b><u>Voice</u></b>

- /vcinfo, /vcmembers - show current voice chat participants.
- /activevc, /activevoice, /vc - list active voice chats.
- /activev, /activevideo, /avc - list active video chats.
- /ac, /av - show active voice/video chat counts.
- /voices [text] - guided TTS voice picker.
- /tts [voice] [text] - direct text-to-speech.
- /voiceall - export the full voice model list.
- /autoend [enable|disable] - auto-leave when the voice chat is empty.
- /botschk - owner checker for monitored bot accounts.
"""

HELP_32 = """
<b><u>Assistant</u></b>

- /assistantjoin, /userbotjoin - invite the assistant account to the chat.
- /userbotleave - remove the assistant from the current chat.
- /link, /invitelink [group id] - export invite/details for another group.
- /leavegroup - make the bot leave the current group.
"""

HELP_33 = """
<b><u>Sudo / Owner</u></b>

- /sudolist, /listsudo, /sudoers - show current sudo users.
- /addsudo [reply/@user/id] - add a sudo user.
- /delsudo, /rmsudo [reply/@user/id] - remove a sudo user.
- /delallsudo - remove every sudo user except the owner.
- /post - copy a replied message to the configured dump/log chat.
- /leaveall - dev-only command to make the assistant leave all chats.
"""
