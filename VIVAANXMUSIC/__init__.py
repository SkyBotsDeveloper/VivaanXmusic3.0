from VIVAANXMUSIC.core.bot import JARVIS
from VIVAANXMUSIC.core.dir import dirr
from VIVAANXMUSIC.core.git import git
from VIVAANXMUSIC.core.userbot import Userbot
from VIVAANXMUSIC.misc import dbb, heroku

from .logging import LOGGER

dirr()
git()
dbb()
heroku()

app = JARVIS()
userbot = Userbot()


from .platforms import *

Apple = AppleAPI()
Carbon = CarbonAPI()
SoundCloud = SoundAPI()
Spotify = SpotifyAPI()
Resso = RessoAPI()
Telegram = TeleAPI()
YouTube = YouTubeAPI()
