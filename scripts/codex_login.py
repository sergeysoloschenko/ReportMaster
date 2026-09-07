"""Authorize the official SDK runtime with a ChatGPT device code."""
from openai_codex import Codex, CodexConfig

with Codex(CodexConfig(config_overrides=('forced_login_method="chatgpt"',))) as codex:
    login = codex.login_chatgpt_device_code()
    print(login.verification_url)
    print(login.user_code)
    login.wait()
    print("Вход выполнен")
