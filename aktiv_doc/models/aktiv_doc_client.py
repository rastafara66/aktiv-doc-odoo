# -*- coding: utf-8 -*-
"""Клієнт API Active Doc v1 — єдине місце, де модуль ходить у мережу.

Контракт — `3A/active-doc-api.md` (веде VPS-Claude, змінюється лише там).

🔴 Ключ організації — лише в заголовку `X-Adoc-Key` і лише з сервера Odoo:
у браузер, у JS і в журнал він не потрапляє ніколи. Вміст документів і дані
контрагентів теж не логуються (обіцянка політики конфіденційності Active Doc):
у журналі — метод, шлях без параметрів, HTTP-статус і код помилки, не більше.

🔴 Текст помилки Active Doc (`message`) — українською для людини, і
показується як є; ми лише дописуємо, що зробити.
"""
import logging
from urllib.parse import urlsplit

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_URL = "https://doc.aktiv.in.ua"
TIMEOUT = 30


def _http(method, url, headers=None, json=None, params=None, timeout=TIMEOUT):
    """Один HTTP-запит. Окремою функцією, щоб тести підміняли саме мережу."""
    return requests.request(method, url, headers=headers, json=json, params=params,
                            timeout=timeout)


class AktivDocError(UserError):
    """Відмова Active Doc або мережі — з кодом, щоб код поруч міг розрізнити причину."""

    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


#: Що зробити — за HTTP-статусом відповіді (контракт, розділ «Головне»).
HOWTO = {
    401: "перевірте ключ API в Налаштуваннях (Виставлення рахунків → Active Doc): "
         "його могли відкликати. Новий ключ створюється в кабінеті Active Doc, "
         "«Організація» → «Ключі API».",
    402: "змініть тариф у кабінеті Active Doc або дочекайтеся наступного місяця — "
         "вхідні документи й підпис працюють і без меж.",
    403: "перевірте ключ API в Налаштуваннях: він має належати цій організації.",
    404: "документа немає в Active Doc для організації цього ключа — можливо, ключ "
         "замінили ключем іншої організації.",
    410: "натисніть «Підписати» ще раз — відкриється нове вікно підпису.",
    429: "зачекайте кілька хвилин і повторіть: Active Doc обмежує кількість запитів.",
}


class AktivDocClient(models.AbstractModel):
    _name = "aktiv.doc.client"
    _description = "Клієнт API Active Doc"

    @api.model
    def _base_url(self, company):
        return (company.sudo().aktiv_doc_url or DEFAULT_URL).strip().rstrip("/")

    @api.model
    def _origin(self, company):
        """`схема://хост[:порт]` сервісу — саме з нього приходить `postMessage` вікна підпису."""
        parts = urlsplit(self._base_url(company))
        return "%s://%s" % (parts.scheme, parts.netloc)

    @api.model
    def _request(self, company, method, path, payload=None, params=None, raw=False,
                 key=None, base_url=None):
        """Запит до API від імені організації. Помилка — `AktivDocError` з поясненням."""
        key = (key or company.sudo().aktiv_doc_key or "").strip()
        if not key:
            raise AktivDocError(_(
                "Active Doc не підключено для організації «%(company)s».\n\n"
                "Чому: без ключа API модуль не може звернутися до Active Doc.\n"
                "Що зробити: адміністратор створює ключ у кабінеті Active Doc "
                "(«Організація» → «Ключі API») і вставляє його в Налаштуваннях: "
                "Виставлення рахунків → Active Doc.", company=company.name), code="ENOKEY")
        base = (base_url or self._base_url(company)).strip().rstrip("/")
        url = "%s/api/v1/%s" % (base, path.lstrip("/"))
        log_path = path.split("?")[0]
        try:
            response = _http(method, url, headers={"X-Adoc-Key": key, "Accept": "application/json"},
                             json=payload, params=params)
        except requests.RequestException as error:
            _logger.warning("Active Doc %s %s: мережа — %s", method, log_path, type(error).__name__)
            raise AktivDocError(_(
                "Немає зв'язку з Active Doc (%(url)s).\n\n"
                "Чому: сервер не відповів або з'єднання перервалося (%(kind)s).\n"
                "Що зробити: перевірте, чи сервер Odoo має доступ до інтернету, і "
                "повторіть за кілька хвилин. Документи в Active Doc від цього не "
                "постраждали.", url=base, kind=type(error).__name__), code="ENETWORK") from None
        status = response.status_code
        if status >= 400:
            code, message = self._error_of(response)
            _logger.info("Active Doc %s %s: %s %s", method, log_path, status, code or "")
            howto = HOWTO.get(status) or _(
                "повторіть пізніше; якщо помилка не зникає — напишіть у підтримку "
                "Active Doc, вказавши код %(code)s.", code=code or status)
            raise AktivDocError(_("%(message)s\n\nЩо зробити: %(howto)s",
                                  message=message, howto=howto), code=code, status=status)
        if raw:
            return response.content
        try:
            return response.json()
        except ValueError:
            _logger.warning("Active Doc %s %s: відповідь не JSON", method, log_path)
            raise AktivDocError(_(
                "Active Doc відповів незрозуміло (не JSON).\n\n"
                "Чому: можливо, у полі «Адреса Active Doc» вказано не ту адресу.\n"
                "Що зробити: перевірте адресу в Налаштуваннях — типово "
                "https://doc.aktiv.in.ua."), code="EFORMAT") from None

    @api.model
    def _error_of(self, response):
        """(код, повідомлення для людини) з тіла помилки `{"error", "message"}`."""
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        code = body.get("error")
        message = body.get("message") or _(
            "Active Doc відхилив запит (HTTP %(status)s).", status=response.status_code)
        return code, message
