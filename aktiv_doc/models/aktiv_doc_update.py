# -*- coding: utf-8 -*-
"""Сказати користувачеві, що вийшла новіша версія «Active Doc» (STORE-CONVENTIONS §8).

🔴 Odoo цього не робить для сторонніх модулів: її «Оновити» порівнює встановлене з
тим, що вже лежить на диску, і ніколи не питає магазин. Покупець зі збіркою з
помилкою жив би з нею вічно.

Перевірка свідомо найменш нав'язлива: GET без тіла й без ідентифікатора (ні бази,
ні версій), раз на добу плановою дією, будь-яка невдача мовчки поглинається.
Банер веде на сторінку магазину — встановити він нічого не може.

Реалізація — з `bank_sync_base/models/bank_sync_update.py` (через «Актив»): там її
відлагоджено на живих інсталяціях. Приймач той самий, `yellow.in.ua/bank-sync/latest`;
`aktiv_doc` у його мапі `_WANTED` (`odoo-bank-sync/tools/report_receiver.py`).
"""
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

PARAM_UPDATE_CHECK = "aktiv_doc.update_check"
PARAM_LATEST = "aktiv_doc.latest_versions"
PARAM_URL = "aktiv_doc.update_url"
PARAM_CHECKED = "aktiv_doc.latest_checked"

DEFAULT_URL = "https://yellow.in.ua/bank-sync/latest"
# Серія в адресі підставляється, а не зашита: інакше банер на іншій серії Odoo
# вів би на збірку, яку ця база не встановить.
STORE_URL = "https://apps.odoo.com/apps/modules/%s/%s/"
CHECK_TIMEOUT = 10

# 🔴 Кожен модуль цього репо — тут. Тест `test_every_module_is_listed` червоніє,
# якщо з'явиться новий, а сюди його не дописали (так у Bank Sync три тижні
# покупці нового конектора не отримували жодного виправлення).
KNOWN_MODULES = ("aktiv_doc",)


def series_of(version):
    """``"19.0.1.2.3"`` → ``"19.0"``. Порожньо, якщо серії в рядку немає."""
    parts = (version or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else ""


def parse_version(text):
    """``"19.0.1.2.10"`` → ``(19, 0, 1, 2, 10)`` — числа, а не текст: як рядок
    ``"…10"`` стоїть нижче за ``"…9"``, і десяте виправлення не пропонувалося б."""
    parts = []
    for chunk in (text or "").split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


class AktivDocUpdate(models.AbstractModel):
    _name = "aktiv.doc.update"
    _description = "Перевірка версії «Active Doc»"

    @api.model
    def _enabled(self):
        # Незаданий параметр — «увімкнено»: запит не несе нічого про користувача.
        return self.env["ir.config_parameter"].sudo().get_param(
            PARAM_UPDATE_CHECK, "on") != "off"

    @api.model
    def _our_series(self):
        module = self.env["ir.module.module"].sudo().search(
            [("name", "in", KNOWN_MODULES), ("state", "=", "installed")], limit=1)
        return series_of(module.installed_version) if module else ""

    @api.model
    def _run_check(self):
        """``(ok, причина)`` — окремо від cron-а, щоб ручна перевірка мала відповідь."""
        if not self._enabled():
            return False, _("Перевірку версій вимкнено.")
        params = self.env["ir.config_parameter"].sudo()
        url = params.get_param(PARAM_URL, DEFAULT_URL)
        if not url:
            return False, _("Адресу перевірки версій не задано.")
        series = self._our_series()

        import requests
        try:
            response = requests.get(url, timeout=CHECK_TIMEOUT,
                                    params={"series": series} if series else None)
            response.raise_for_status()
            published = response.json()
        except Exception as error:  # noqa: BLE001 — пропущена перевірка не подія
            return False, _("Не вдалося звернутись до %(url)s: %(error)s", url=url,
                            error=type(error).__name__)
        if not isinstance(published, dict):
            return False, _("%s відповів не переліком версій.", url)
        # Фільтр і на відповіді: параметр серії — прохання, а не гарантія.
        clean = {name: str(published[name])[:32] for name in KNOWN_MODULES
                 if isinstance(published.get(name), str)
                 and (not series or series_of(published[name]) == series)}
        if not clean:
            return False, _("%s не знає про ці модулі.", url)
        params.set_param(PARAM_LATEST, json.dumps(clean))
        params.set_param(PARAM_CHECKED, fields.Datetime.to_string(fields.Datetime.now()))
        return True, ""

    @api.model
    def _cron_check(self):
        """Добова задача: ніколи не падає, тихо оновлює кеш."""
        ok, reason = self._run_check()
        if not ok and reason:
            _logger.info("Перевірку версії «Active Doc» пропущено: %s", reason)
        return ok

    @api.model
    def _published(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_LATEST)
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    @api.model
    def _outdated(self):
        """``[(модуль, встановлено, опубліковано)]`` — лише своєї серії й новіші числами."""
        published = self._published()
        if not published:
            return []
        out = []
        for module in self.env["ir.module.module"].sudo().search(
                [("name", "in", KNOWN_MODULES), ("state", "=", "installed")]):
            latest = published.get(module.name)
            if not latest or series_of(latest) != series_of(module.installed_version):
                continue
            if parse_version(latest) > parse_version(module.installed_version):
                out.append((module.name, module.installed_version, latest))
        return out

    @api.model
    def update_banner(self):
        """Текст банера й посилання, або ``(False, False)``."""
        outdated = self._outdated()
        if not outdated:
            return False, False
        name, installed, latest = outdated[0]
        return _("Вийшла новіша версія «Active Doc»: %(latest)s (у вас %(installed)s).",
                 latest=latest, installed=installed), \
            STORE_URL % (series_of(installed) or "19.0", name)


class AktivDocDocumentUpdateBanner(models.Model):
    """Банер — на картці документа: туди людина заходить щоразу, коли підписує."""
    _inherit = "aktiv.doc.document"

    update_message = fields.Char(compute="_compute_update_message",
                                 help="Повідомлення про нову версію «Active Doc», якщо вона вийшла.")
    update_url = fields.Char(compute="_compute_update_message",
                             help="Де взяти нову версію — сторінка магазину Odoo.")

    def _compute_update_message(self):
        message, url = self.env["aktiv.doc.update"].update_banner()
        for record in self:
            record.update_message = message
            record.update_url = url
