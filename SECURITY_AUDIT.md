# Security Audit

Date: 2026-02-05
Scope: command injection / shell execution and minimal safety hardening per request.

## Findings

1) Playlist command injection via yt-dlp shell invocation
File: `VIVAANXMUSIC/platforms/Youtube.py:239-266`
Issue: Playlist URL was interpolated into a shell command.
Patch: Replaced shell execution with list-args execution and added minimal URL character blocking (`; & | $ \n \r `).

2) Shell execution in ffmpeg speedup
File: `VIVAANXMUSIC/core/call.py:176-185`
Issue: ffmpeg command built as a shell string.
Patch: Use `create_subprocess_exec` with shlex-split args.

3) os.system use in update/restart commands
File: `VIVAANXMUSIC/plugins/sudo/restart.py:73-155`
Issue: git and heroku commands executed via shell (heroku push includes API key in command string).
Patch: Use `subprocess.run` with list args and suppress output.

4) os.system in video editing
File: `VIVAANXMUSIC/plugins/tools/videoedit.py:50-61`
Issue: ffmpeg command executed via shell.
Patch: Use `subprocess.run` with list args.

5) os.system in tiny sticker conversion
File: `VIVAANXMUSIC/plugins/tools/tiny.py:34-40`
Issue: lottie_convert commands executed via shell.
Patch: Use `subprocess.run` with list args.

## Secrets
`.env` is already gitignored and no `.env` file exists in the repo.

## Tests
`python -m py_compile VIVAANXMUSIC/platforms/Youtube.py`
`python -m py_compile VIVAANXMUSIC/core/call.py`
`python -m py_compile VIVAANXMUSIC/plugins/sudo/restart.py`
`python -m py_compile VIVAANXMUSIC/plugins/tools/videoedit.py VIVAANXMUSIC/plugins/tools/tiny.py`
