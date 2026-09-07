#!/usr/bin/env python3
"""Store an Exchange password without shell-history or terminal echo exposure."""
import getpass
import os
from pathlib import Path

path = Path("data/history/ews_password")
path.parent.mkdir(parents=True, exist_ok=True)
secret = getpass.getpass("Пароль Exchange для spectrum\\soloshchenko: ")
if not secret:
    raise SystemExit("Пароль не изменён: пустое значение")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write(secret)
print("Пароль сохранён. Укажите EWS_PASSWORD_FILE=data/history/ews_password в .env.")
