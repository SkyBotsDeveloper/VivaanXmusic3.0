from VIVAANXMUSIC.core.bot import JARVIS
from VIVAANXMUSIC.core.dir import dirr
from VIVAANXMUSIC.core.git import git
from VIVAANXMUSIC.core.userbot import Userbot
from VIVAANXMUSIC.misc import dbb, heroku
from VIVAANXMUSIC.security import drop_sensitive_env_vars

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

_removed_sensitive_env = drop_sensitive_env_vars()
if _removed_sensitive_env:
    LOGGER(__name__).info(
        "Security hardening active: stripped %s sensitive env vars from process environment.",
        len(_removed_sensitive_env),
    )
