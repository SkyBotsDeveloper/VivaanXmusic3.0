from pyrogram.types import CallbackQuery
from pyrogram.enums import ChatType, ChatMemberStatus

async def is_admin(message_or_cq) -> bool:
    if isinstance(message_or_cq, CallbackQuery):
        message = message_or_cq.message
        user = message_or_cq.from_user
    else:
        message = message_or_cq
        user = message.from_user

    if not user or message.sender_chat:
        return False

    if message.chat.type not in [ChatType.SUPERGROUP, ChatType.CHANNEL, ChatType.GROUP]:
        return False

    client = message._client
    member = await client.get_chat_member(message.chat.id, user.id)
    return member.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]

async def is_group_owner(message_or_cq) -> bool:
    if isinstance(message_or_cq, CallbackQuery):
        message = message_or_cq.message
        user = message_or_cq.from_user
    else:
        message = message_or_cq
        user = message.from_user

    if not user or message.sender_chat:
        return False

    if message.chat.type not in [ChatType.SUPERGROUP, ChatType.CHANNEL, ChatType.GROUP]:
        return False

    client = message._client
    member = await client.get_chat_member(message.chat.id, user.id)
    return member.status == ChatMemberStatus.OWNER
