"""Bounded user identity cache fed by Telegram's own update metadata."""
import asyncio
import time
from collections import OrderedDict
from html import escape


class VcIdentityResolver:
    def __init__(self, limit=2048, ttl=900):
        self.limit, self.ttl = limit, ttl
        self.cache = OrderedDict()
        self.lock = asyncio.Semaphore(4)

    def remember(self, users):
        for user in users.values() if isinstance(users, dict) else users or ():
            user_id = getattr(user, "id", None)
            if not user_id:
                continue
            name = " ".join(part for part in (
                getattr(user, "first_name", None), getattr(user, "last_name", None)
            ) if part).strip()
            username = getattr(user, "username", None)
            if not username:
                username = next((item.username for item in getattr(user, "usernames", None) or ()
                                 if getattr(item, "active", False)), None)
            if getattr(user, "min", False) and not username:
                previous = self.cached(int(user_id))
                username = previous[1] if previous else None
            if not name and not username:
                continue
            self.cache[int(user_id)] = (time.monotonic() + self.ttl, name, username)
            self.cache.move_to_end(int(user_id))
            while len(self.cache) > self.limit:
                self.cache.popitem(last=False)

    def cached(self, user_id):
        entry = self.cache.get(user_id)
        if entry and entry[0] > time.monotonic():
            return entry[1:]
        self.cache.pop(user_id, None)
        return None

    async def resolve(self, user_id, clients):
        cached = self.cached(user_id)
        if cached:
            return cached
        async with self.lock:
            if cached := self.cached(user_id):
                return cached
            for client in clients:
                if client is None:
                    continue
                try:
                    user = await asyncio.wait_for(client.get_users(user_id), timeout=3)
                    if getattr(user, "id", None) == user_id:
                        self.remember([user])
                        if cached := self.cached(user_id):
                            return cached
                except Exception:
                    continue
            # Avoid retry storms for deleted/inaccessible accounts. Never invent
            # a name: a numeric identity is still unambiguous.
            self.cache[user_id] = (time.monotonic() + 30, str(user_id), None)
            while len(self.cache) > self.limit:
                self.cache.popitem(last=False)
            return str(user_id), None


def vc_join_text(source_chat_id, user_id, name, username=None, *, external=False):
    heading = f"Joined VC\nGroup ID: <code>{source_chat_id}</code>\n" if external else "Joined VC\n"
    username_text = f"\nUsername: @{escape(username)}" if username else ""
    # tg://user mentions require the sending bot to know the peer access hash.
    # Assistant-only identities must still render when the bot lacks that peer.
    return (heading + f"Name: <b>{escape(name or str(user_id))}</b>"
            + username_text + f"\nUser ID: <code>{user_id}</code>")
