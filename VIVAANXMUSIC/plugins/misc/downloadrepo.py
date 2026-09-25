import os
import shutil
import tempfile
import asyncio

import git
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.misc import SUDOERS
from VIVAANXMUSIC.security import (
    SecurityError,
    build_subprocess_env,
    validate_github_repo_url,
)


@app.on_message(filters.command(["downloadrepo"]) & SUDOERS)
async def download_repo(client: Client, message: Message):
    if len(message.command) != 2:
        return await message.reply_text(
            "Please provide a GitHub repository URL.\n\n"
            "Example: `/downloadrepo https://github.com/VivaanNetworkDev/VivaanXmusic3.0`",
            parse_mode=ParseMode.MARKDOWN,
        )

    repo_url = message.command[1]
    status_msg = await message.reply_text("Cloning the repository...")
    cleanup_dir = None

    try:
        zip_path, cleanup_dir = await clone_and_zip_repo(repo_url)
        await message.reply_document(
            zip_path,
            caption="Repository downloaded and zipped.",
        )
    except SecurityError as exc:
        await message.reply_text(
            f"Blocked by security policy: `{exc}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except git.exc.GitCommandError:
        await message.reply_text(
            "Unable to download the specified GitHub repository.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        await message.reply_text(
            f"Failed to prepare repository archive: `{exc}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    finally:
        if cleanup_dir and os.path.exists(cleanup_dir):
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        await status_msg.delete()


async def clone_and_zip_repo(repo_url: str) -> tuple[str, str]:
    safe_repo_url = validate_github_repo_url(repo_url)

    temp_root = tempfile.mkdtemp(prefix="vivaan_repo_")
    repo_name = safe_repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    repo_path = os.path.join(temp_root, repo_name)
    archive_base = os.path.join(temp_root, repo_name)

    try:
        return await asyncio.to_thread(
            _clone_and_zip_repo_sync,
            safe_repo_url,
            repo_path,
            archive_base,
            temp_root,
        )
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def _clone_and_zip_repo_sync(
    safe_repo_url: str,
    repo_path: str,
    archive_base: str,
    temp_root: str,
) -> tuple[str, str]:
    git.Repo.clone_from(
        safe_repo_url,
        repo_path,
        env=build_subprocess_env(),
        multi_options=["--depth=1", "--single-branch"],
    )
    zip_file = shutil.make_archive(archive_base, "zip", repo_path)
    return zip_file, temp_root
