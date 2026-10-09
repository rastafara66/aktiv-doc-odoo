# -*- coding: utf-8 -*-
"""Документ ЕДО — дзеркало документа Active Doc у базі Odoo.

Джерело правди — Active Doc: стан, підписи, квоти. Тут — лише копія, яку
оновлює відповідь API (після кожної дії й щоп'ять хвилин cron-ом), і зв'язок
із записом обліку (`record_ref`), з якого документ надіслано.

🔴 Повідомленню з браузера «підписано» на слово не віримо: вікно підпису
лише просить сервер перепитати Active Doc (`action_refresh`).

Документ — файл, а не обов'язково PDF рахунку: етап 2 (звітність до ДПС)
піде тим самим шляхом із XML, тому модель не прив'язана до звіту Odoo.
"""
import base64
import logging
import re
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .aktiv_doc_client import AktivDocError
from ..tools.series import partner_code_fields, registry_label

_logger = logging.getLogger(__name__)

STATES = [
    ("draft", "Чернетка"),
    ("signed", "Підписано відправником"),
    ("sent", "Надіслано, чекає підпису отримувача"),
    ("done", "Підписано обома сторонами"),
    ("rejected", "Відхилено"),
]
#: ЄДРПОУ — 8 цифр, РНОКПП — 10. 🔴 `[0-9]`, а не `\d`: `\d` у Python пропускає цифри
#: інших письмен («١٢٣…»), і Active Doc відкинув би такий код з незрозумілою людині причиною.
CODE_RE = re.compile(r"^([0-9]{8}|[0-9]{10})$")
#: Стан документа Active Doc → стан у колонці «Active Doc» списку рахунків.
RECORD_STATE = {"draft": "waiting", "signed": "signed", "sent": "sent", "done": "done",
                "rejected": "rejected"}
#: Скільки сторінок змін забирати за один прогін cron-а (по 200 документів).
SYNC_PAGES = 20


def _parse_time(value):
    """ISO-час Active Doc (`2026-10-06T14:50:00Z`) → наївний UTC, як зберігає Odoo."""
    if not value:
        return False
    try:
        return datetime.strptime(value.replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False


def format_problems(env, header, problems):
    """Усі проблеми одразу (§9): що / чому / що зробити."""
    lines = [header, env._("Знайдено проблем: %(n)d", n=len(problems))]
    for number, (what, why, howto) in enumerate(problems, 1):
        lines.append(env._("\n%(n)d. %(what)s\n   Чому: %(why)s\n   Що зробити: %(howto)s",
                           n=number, what=what, why=why, howto=howto))
    return "\n".join(lines)


class AktivDocDocument(models.Model):
    _name = "aktiv.doc.document"
    _inherit = ["mail.thread"]
    _description = "Документ Active Doc"
    _order = "adoc_changed desc, id desc"
    _check_company_auto = True

    # Odoo 18: `_sql_constraints` (у 19 — `models.Constraint`).
    _sql_constraints = [(
        "adoc_uniq",
        "UNIQUE(company_id, adoc_id)",
        "Цей документ Active Doc уже є в базі для цієї організації. Кожен документ "
        "сервісу має в Odoo рівно один запис — інакше стани розійдуться. Відкрийте "
        "наявний запис у «Документообіг» замість того, щоб створювати новий.",
    )]

    name = fields.Char("Документ", required=True, tracking=True,
                       help="Назва документа, як її бачить контрагент в Active Doc.")
    company_id = fields.Many2one("res.company", string="Організація", required=True,
                                 default=lambda s: s.env.company, index=True,
                                 help="Чия організація в Active Doc надсилає чи отримує документ.")
    adoc_id = fields.Integer("Номер в Active Doc", readonly=True, copy=False, index=True,
                             help="Ідентифікатор документа в сервісі Active Doc.")
    direction = fields.Selection([("out", "Вихідний"), ("in", "Вхідний")], string="Напрям",
                                 required=True, default="out", readonly=True,
                                 help="Вихідний — ми надсилаємо контрагенту; вхідний — "
                                      "контрагент надіслав нам.")
    # Без tracking: зміну стану пише `_post_event` словами Active Doc («Підписано 1 з 2»),
    # а відстеження поля дублювало кожну подію другим записом у стрічці.
    state = fields.Selection(STATES, string="Стан", default="draft", required=True,
                             readonly=True,
                             help="Стан документа в Active Doc. Оновлюється сам кожні "
                                  "кілька хвилин і після кожної дії.")
    state_label = fields.Char("Що з документом", readonly=True,
                              help="Стан словами від Active Doc — зокрема «Підписано 1 з 2», "
                                   "коли організація вимагає два підписи.")
    can_sign = fields.Boolean("Можна підписати зараз", readonly=True,
                              help="Чи може наша організація підписати документ саме зараз. "
                                   "Лише тоді є кнопка «Підписати».")
    record_ref = fields.Reference(selection="_selection_record_model", string="Документ обліку",
                                  readonly=True, index=True,
                                  help="Рахунок, акт чи накладна, з яких надіслано документ. "
                                       "Натисніть, щоб відкрити.")
    partner_id = fields.Many2one("res.partner", string="Контрагент", check_company=True,
                                 index=True,
                                 help="Контрагент у базі Odoo — знайдений за кодом ЄДРПОУ / "
                                      "РНОКПП або взятий із документа обліку.")
    counterparty_name = fields.Char("Назва контрагента", readonly=True,
                                    help="Назва другої сторони, як її знає Active Doc.")
    counterparty_code = fields.Char("Код контрагента", readonly=True,
                                    help="ЄДРПОУ (8 цифр) або РНОКПП (10 цифр) другої сторони.")
    counterparty_email = fields.Char("Пошта контрагента", readonly=True,
                                     help="Куди Active Doc надіслав лист із посиланням, якщо в "
                                          "контрагента немає кабінету.")
    in_cabinet = fields.Boolean("Контрагент має кабінет", readonly=True,
                                help="Так — документ лежить у його вхідних в Active Doc; ні — "
                                     "він отримує посилання й підписує без реєстрації.")
    file_name = fields.Char("Файл", readonly=True, help="Ім'я файлу документа.")
    sha256 = fields.Char("Контрольна сума", readonly=True,
                         help="SHA-256 файлу — за нею перевіряють, що підписано саме цей файл.")
    attachment_id = fields.Many2one("ir.attachment", string="Файл документа", readonly=True,
                                    copy=False, help="Сам документ (PDF), який підписують.")
    archive_id = fields.Many2one("ir.attachment", string="Архів із підписами", readonly=True,
                                 copy=False,
                                 help="ZIP: документ, підпис кожної особи окремим файлом і "
                                      "протокол перевірки — юридично значуща копія. "
                                      "З'являється, коли підписали обидві сторони.")
    signs_needed = fields.Char("Скільки підписів потрібно", readonly=True,
                               help="Скільки осіб від кожної сторони мають підписати.")
    signatures = fields.Text("Підписи", readonly=True,
                             help="Хто, коли і яким ключем підписав — за даними Active Doc.")
    reject_reason = fields.Text("Причина відмови", readonly=True,
                                help="Чому документ відхилено.")
    external_ref = fields.Char("Посилання на запис", readonly=True, copy=False,
                               help="Службове: база, модель і номер запису обліку — так "
                                    "Active Doc повертає документ до свого запису.")
    adoc_changed = fields.Datetime("Змінено", readonly=True,
                                   help="Коли документ востаннє змінювався в Active Doc.")

    @api.model
    def _selection_record_model(self):
        return [(model.model, model.name) for model in self.env["ir.model"].sudo().search([])]

    @api.model_create_multi
    def create(self, vals_list):
        docs = super().create(vals_list)
        docs._sync_record_state()
        return docs

    def write(self, vals):
        result = super().write(vals)
        if {"state", "record_ref"} & set(vals):
            self._sync_record_state()
        return result

    def _sync_record_state(self):
        """Стан останнього вихідного документа — у колонку «Active Doc» запису обліку.

        Власник в «Рахівнику» стану на вкладці не помітив («не бачу»): його треба бачити
        в СПИСКУ рахунків поряд зі «Стан». Тому поле збережене — фільтрується й групується.
        """
        for doc in self.filtered(lambda d: d.direction == "out"):
            record = doc._record()
            if not record or "aktiv_doc_state" not in record._fields:
                continue
            latest = self.search([("record_ref", "=", "%s,%s" % (record._name, record.id))],
                                 order="id desc", limit=1)
            value = RECORD_STATE.get(latest.state) or False
            if record.aktiv_doc_state != value:
                record.sudo().write({"aktiv_doc_state": value})

    # ------------------------------------------------------------------
    # Відповідь API → поля
    # ------------------------------------------------------------------
    @api.model
    def _format_signatures(self, signatures):
        side = {"sender": _("відправник"), "recipient": _("отримувач")}
        lines = []
        for sign in signatures:
            who = ", ".join(part for part in (sign.get("name"), sign.get("title")) if part)
            org = sign.get("org") or ""
            if sign.get("org_code"):
                org = "%s (%s)" % (org, sign["org_code"])
            moment = _parse_time(sign.get("time"))
            when = ""
            if moment:
                # Час — у поясі користувача, а без нього (cron) — київський: КЕП українські,
                # і текст не має залежати від того, хто саме синхронізував.
                tz = self.env.context.get("tz") or self.env.user.tz or "Europe/Kyiv"
                local = fields.Datetime.context_timestamp(self.with_context(tz=tz), moment)
                when = " · %s" % local.strftime("%d.%m.%Y %H:%M")
            lines.append("%s: %s%s%s%s" % (
                side.get(sign.get("side"), sign.get("side") or "?"), who or "?",
                " — %s" % org if org.strip() else "",
                when,
                _(" · тестовий ключ") if sign.get("test_key") else ""))
        return "\n".join(lines) or False

    @api.model
    def _vals_from_api(self, data):
        direction = data.get("direction") if data.get("direction") in ("out", "in") else "out"
        other = (data.get("recipient") if direction == "out" else data.get("sender")) or {}
        needed = data.get("signs_needed") or {}
        vals = {
            "adoc_id": data.get("id"),
            "direction": direction,
            "state_label": data.get("state_label") or False,
            "can_sign": bool(data.get("can_sign")),
            "file_name": data.get("file_name") or False,
            "sha256": data.get("sha256") or False,
            "signs_needed": _("відправник — %(s)s, отримувач — %(r)s",
                              s=needed.get("sender", "?"), r=needed.get("recipient", "?"))
                            if needed else False,
            "signatures": self._format_signatures(data.get("signatures") or []),
            "reject_reason": data.get("reject_reason") or False,
            "external_ref": data.get("external_ref") or False,
            "adoc_changed": _parse_time(data.get("changed")),
        }
        # 🔴 Друга сторона — лише якщо Active Doc її вже знає: до «Надіслати» отримувача
        # там немає, і порожня відповідь стерла б вибраного в майстрі контрагента.
        if other.get("code") or other.get("name"):
            vals.update({
                "counterparty_name": other.get("name") or False,
                "counterparty_code": other.get("code") or False,
                "in_cabinet": bool(other.get("in_cabinet")),
            })
        if data.get("name"):
            vals["name"] = data["name"]
        if data.get("state") in dict(STATES):
            vals["state"] = data["state"]
        return vals

    @api.model
    def _partner_by_code(self, code, company):
        """Контрагент за ЄДРПОУ / РНОКПП: у базах буває заповнене одне з полів (ті, що є в
        базі: в Odoo 20 «Реєстру компанії» немає)."""
        if not code:
            return self.env["res.partner"]
        Partner = self.env["res.partner"].with_context(active_test=True)
        names = partner_code_fields(self.env)
        domain = ["|"] * (len(names) - 1) + [(name, "=", code) for name in names] \
            + [("company_id", "in", [company.id, False])]
        partners = Partner.search(domain, limit=5)
        return (partners.filtered(lambda p: not p.parent_id) or partners)[:1]

    def _record(self):
        """Запис обліку, якщо він ще існує й доступний."""
        self.ensure_one()
        record = self.record_ref
        return record.exists() if record else None

    def _post_event(self, body):
        """Подія — у стрічку документа й у стрічку запису обліку."""
        for doc in self:
            doc.message_post(body=body)
            record = doc._record()
            if record and hasattr(record, "message_post"):
                record.message_post(body=_("Active Doc, «%(doc)s»: %(event)s",
                                           doc=doc.name, event=body))

    def _apply_api(self, data):
        """Записати відповідь API в документ і відзначити зміну стану."""
        self.ensure_one()
        before = (self.state, self.state_label)
        vals = self._vals_from_api(data)
        if not self.partner_id and vals.get("counterparty_code"):
            partner = self._partner_by_code(vals["counterparty_code"], self.company_id)
            if partner:
                vals["partner_id"] = partner.id
        self.write(vals)
        if (self.state, self.state_label) != before:
            self._post_event(self.state_label or dict(STATES)[self.state])
        if self.state == "done" and not self.archive_id:
            self._fetch_archive()
        return True

    def _client(self):
        return self.env["aktiv.doc.client"]

    def _attach(self, content, name, mimetype, res_model=None, res_id=None):
        return self.env["ir.attachment"].sudo().create({
            "name": name,
            "raw": content,
            "mimetype": mimetype,
            "res_model": res_model or self._name,
            "res_id": res_id or self.id,
            "company_id": self.company_id.id,
        })

    def _fetch_archive(self):
        """Архів обох підписів — до документа й до запису обліку (юридично значуща копія)."""
        self.ensure_one()
        content = self._client()._request(self.company_id, "GET",
                                          "documents/%d/archive" % self.adoc_id, raw=True)
        name = _("%s — підписаний архів.zip", self.name)
        self.archive_id = self._attach(content, name, "application/zip")
        record = self._record()
        if record:
            self._attach(content, name, "application/zip", record._name, record.id)

    def _fetch_file(self):
        """Файл вхідного документа — щоб його можна було переглянути в Odoo."""
        self.ensure_one()
        content = self._client()._request(self.company_id, "GET",
                                          "documents/%d/file" % self.adoc_id, raw=True)
        self.attachment_id = self._attach(content, self.file_name or "%s.pdf" % self.name,
                                          "application/pdf")

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------
    def action_refresh(self):
        """«Оновити» — перепитати Active Doc про стан. Викликає й вікно підпису."""
        for doc in self.filtered("adoc_id"):
            data = doc._client()._request(doc.company_id, "GET", "documents/%d" % doc.adoc_id)
            doc._apply_api(data)
        return True

    def action_sign(self):
        """«Підписати» — одноразове вікно підпису Active Doc усередині Odoo."""
        self.ensure_one()
        # 🔴 Стан — завжди з Active Doc: збережене тут «можна підписати» могло
        # застаріти (підписала друга особа, контрагент відхилив).
        self.action_refresh()
        if not self.can_sign:
            raise UserError(_(
                "Зараз підписати «%(doc)s» не можна: %(state)s.\n\n"
                "Чому: Active Doc дозволяє підпис лише стороні, черга якої підписувати "
                "(а якщо потрібно два підписи — іншій особі, ніж перша).\n"
                "Що зробити: дочекайтеся підпису другої сторони або попросіть підписати "
                "другу відповідальну особу.",
                doc=self.name, state=self.state_label or dict(STATES)[self.state]))
        session = self._client()._request(self.company_id, "POST",
                                          "documents/%d/sign_session" % self.adoc_id, payload={})
        return {
            "type": "ir.actions.client",
            "tag": "aktiv_doc_sign",
            "params": {
                "url": session.get("url"),
                # Звідки чекати `postMessage` — сам сервіс, а не дозволена адреса ключа.
                "origin": self._client()._origin(self.company_id),
                # Звідки дозволено вбудовувати вікно — для зрозумілої відмови, якщо не звідси.
                "allowed_origin": session.get("origin") or "",
                "adoc_id": self.adoc_id,
                "doc_id": self.id,
                "title": _("Підпис КЕП: %s", self.name),
            },
        }

    def _send_problems(self):
        self.ensure_one()
        problems = []
        if self.direction != "out":
            problems.append((_("«%s» — вхідний документ", self.name),
                             _("надсилати можна лише свої документи"),
                             _("підпишіть його або відхиліть")))
        elif self.state != "signed":
            problems.append((_("«%(doc)s»: %(state)s", doc=self.name,
                               state=self.state_label or dict(STATES)[self.state]),
                             _("надіслати можна документ, який ми вже підписали й ще не "
                               "надсилали"),
                             _("спершу натисніть «Підписати»") if self.state == "draft"
                             else _("нічого робити не треба — документ уже надіслано")))
        code = (self.counterparty_code or "").strip()
        if not code:
            problems.append((_("Не вказано код отримувача"),
                             _("Active Doc шукає кабінет контрагента за ЄДРПОУ чи РНОКПП"),
                             _("впишіть ЄДРПОУ (поле «%s») або РНОКПП у картку "
                               "контрагента й створіть документ заново",
                               registry_label(self.env))))
        elif not CODE_RE.match(code):
            problems.append((_("Код отримувача «%s» — не ЄДРПОУ і не РНОКПП", code),
                             _("ЄДРПОУ має 8 цифр, РНОКПП — 10"),
                             _("виправте код у картці контрагента й створіть документ заново")))
        return problems

    def action_send(self):
        """«Надіслати» — контрагенту в кабінет за кодом або листом із посиланням."""
        self.ensure_one()
        problems = self._send_problems()
        if problems:
            raise UserError(format_problems(self.env, _("«%s» не надіслано.", self.name), problems))
        data = self._client()._request(self.company_id, "POST", "documents/%d/send" % self.adoc_id,
                                       payload={"code": self.counterparty_code.strip(),
                                                "name": self.counterparty_name or "",
                                                "email": self.counterparty_email or ""})
        self._apply_api(data)
        return True

    def action_reject_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Відхилити документ"),
            "res_model": "aktiv.doc.reject",
            "view_mode": "form",
            "target": "new",
            "context": {"default_document_id": self.id},
        }

    def _reject(self, reason):
        self.ensure_one()
        if self.direction != "in":
            raise UserError(_(
                "Відхилити можна лише вхідний документ.\n\n"
                "Чому: свій документ ми не відхиляємо — його просто не надсилають.\n"
                "Що зробити: якщо документ помилковий, створіть новий із виправленого запису."))
        data = self._client()._request(self.company_id, "POST",
                                       "documents/%d/reject" % self.adoc_id,
                                       payload={"reason": reason})
        self._apply_api(data)

    def action_open_record(self):
        self.ensure_one()
        record = self._record()
        if not record:
            raise UserError(_(
                "Документа обліку для «%s» немає.\n\n"
                "Чому: документ прийшов від контрагента або запис обліку видалено.\n"
                "Що зробити: відкрийте файл документа нижче.", self.name))
        return {"type": "ir.actions.act_window", "res_model": record._name,
                "res_id": record.id, "view_mode": "form", "target": "current"}

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        used = self.filtered(lambda d: d.state != "draft")
        if used:
            raise UserError(_(
                "Документ, який уже підписували, видалити не можна: %(names)s.\n\n"
                "Чому: це запис юридично значущого обміну, і в Active Doc він лишається.\n"
                "Що зробити: залиште запис; якщо документ помилковий, створіть новий.",
                names=", ".join(used.mapped("name"))))

    # ------------------------------------------------------------------
    # Синхронізація: вхідні й зміни стану
    # ------------------------------------------------------------------
    @api.model
    def action_sync_now(self):
        """«Оновити зараз» на списку — те саме, що робить cron, для поточної організації."""
        self._sync_company(self.env.company)
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    @api.model
    def _cron_sync(self):
        companies = self.env["res.company"].sudo().search([]).filtered("aktiv_doc_key")
        for company in companies:
            try:
                self.with_company(company)._sync_company(company)
            except AktivDocError as error:
                # Одна організація без зв'язку не зупиняє решту; причина — у журналі,
                # без тексту документів.
                _logger.warning("Active Doc: синхронізація організації %s не вдалась (%s)",
                                company.id, error.code or error.status)

    @api.model
    def _sync_company(self, company):
        if not company.sudo().aktiv_doc_key:
            raise UserError(_(
                "Active Doc не підключено для організації «%s».\n\n"
                "Що зробити: вставте ключ API в Налаштуваннях: Виставлення рахунків → "
                "Active Doc.", company.name))
        cursor = company.sudo().aktiv_doc_cursor
        client = self._client()
        for _page in range(SYNC_PAGES):
            data = client._request(company, "GET", "documents",
                                   params={"changed_since": cursor} if cursor else None)
            for item in data.get("documents") or []:
                self._upsert_from_api(company, item)
            cursor = data.get("next") or cursor
            if not data.get("more"):
                break
        company.sudo().aktiv_doc_cursor = cursor
        return True

    @api.model
    def _record_from_ref(self, external_ref):
        """Запис обліку з `external_ref`, якщо документ створено з ЦІЄЇ бази."""
        parts = (external_ref or "").split("·")
        uuid = self.env["ir.config_parameter"].sudo().get_param("database.uuid")
        if len(parts) != 3 or parts[0] != uuid or parts[1] not in self.env:
            return None
        try:
            record = self.env[parts[1]].browse(int(parts[2])).exists()
        except ValueError:
            return None
        return record or None

    @api.model
    def _upsert_from_api(self, company, data):
        doc = self.search([("company_id", "=", company.id), ("adoc_id", "=", data.get("id"))],
                          limit=1)
        if doc:
            doc._apply_api(data)
            return doc
        if data.get("direction") == "in" and not company.aktiv_doc_inbox:
            return doc
        vals = self._vals_from_api(data)
        vals["company_id"] = company.id
        vals.setdefault("name", data.get("file_name") or _("Документ %s", data.get("id")))
        partner = self._partner_by_code(vals.get("counterparty_code"), company)
        if partner:
            vals["partner_id"] = partner.id
        record = self._record_from_ref(vals.get("external_ref"))
        if record:
            vals["record_ref"] = "%s,%s" % (record._name, record.id)
        doc = self.create(vals)
        if doc.direction == "in":
            doc.message_post(body=_("Вхідний документ від %(who)s: %(state)s",
                                    who=doc.counterparty_name or doc.counterparty_code or "?",
                                    state=doc.state_label or dict(STATES)[doc.state]))
            try:
                doc._fetch_file()
            except AktivDocError as error:
                _logger.info("Active Doc: файл документа %s не отримано (%s)", doc.adoc_id,
                             error.code or error.status)
        if doc.state == "done" and not doc.archive_id:
            doc._fetch_archive()
        return doc

    # ------------------------------------------------------------------
    # Створення з запису обліку (майстер «Надіслати на підпис»)
    # ------------------------------------------------------------------
    @api.model
    def _create_from_record(self, record, pdf, file_name, name, partner, code, counterparty,
                            email):
        company = record.company_id if "company_id" in record._fields and record.company_id \
            else self.env.company
        uuid = self.env["ir.config_parameter"].sudo().get_param("database.uuid")
        data = self._client()._request(company, "POST", "documents", payload={
            "name": name,
            "file_name": file_name,
            "file": base64.b64encode(pdf).decode("ascii"),
            "external_ref": "%s·%s·%s" % (uuid, record._name, record.id),
        })
        vals = self._vals_from_api(data)
        vals.update({
            "company_id": company.id,
            "name": vals.get("name") or name,
            "record_ref": "%s,%s" % (record._name, record.id),
            "partner_id": partner.id if partner else False,
            # Отримувач — наш вибір у майстрі: Active Doc дізнається його лише на «Надіслати».
            "counterparty_code": code,
            "counterparty_name": counterparty,
            "counterparty_email": email or False,
        })
        doc = self.create(vals)
        doc.attachment_id = doc._attach(pdf, file_name, "application/pdf")
        doc._post_event(_("документ передано в Active Doc для підпису"))
        return doc
