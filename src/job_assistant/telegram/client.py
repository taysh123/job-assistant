"""Thin Telegram Bot API wrapper (requests-based).

Deliberately minimal: only the handful of methods this app needs. Stateless,
so it works equally well in a one-shot GitHub Actions run as locally.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, chat_id: str, *, timeout: int = 30,
                 session: requests.Session | None = None):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self._session = session or requests.Session()

    # --- low level -------------------------------------------------------

    def _call(self, method: str, **params) -> dict:
        url = API_BASE.format(token=self.token, method=method)
        resp = self._session.post(url, json=params, timeout=self.timeout)
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description', data)}")
        return data["result"]

    # --- messages --------------------------------------------------------

    def send_message(self, text: str, *, reply_markup: dict | None = None,
                     disable_preview: bool = True, chat_id: str | None = None) -> dict:
        params = {
            "chat_id": chat_id or self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendMessage", **params)

    def edit_message_text(self, message_id: int, text: str, *,
                          reply_markup: dict | None = None,
                          chat_id: str | None = None) -> dict:
        params = {
            "chat_id": chat_id or self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return self._call("editMessageText", **params)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        # Late answers (after our cron delay) raise "query is too old"; ignore.
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_query_id, text=text)
        except TelegramError as exc:  # pragma: no cover - network edge
            logger.debug("answerCallbackQuery ignored: %s", exc)

    # --- polling ---------------------------------------------------------

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict]:
        params: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", **params)
