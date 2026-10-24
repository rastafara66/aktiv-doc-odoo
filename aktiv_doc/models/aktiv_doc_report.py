# -*- coding: utf-8 -*-
"""Звіт до ДПС через Active Doc — дзеркало звіту кабінету в базі Odoo.

Контракт — `3A/active-doc-api.md`, розділ «Звітність до ДПС» (кабінет 19.0.0.23.0).
Шлях: XML звіту (головний документ і додатки) → `POST reports` → вікно Active Doc усередині
Odoo, де людина СВОЇМ ключем підписує, шифрує й надсилає звіт до ДПС (ключ і пароль не
залишають doc.aktiv.in.ua) → квитанції ДПС.

🔴 Модуль не знає, які звіти бувають: файли дає той, хто надсилає, — будь-який модуль (у
нас — «Актив»: декларації з ПДВ і з прибутку, Об'єднана). «Актив Doc» від нього не залежить і
навпаки; домовленість — три назви:

* `env["aktiv.doc.report"]._aktiv_doc_submit(record, packages, title)` → дія (вікно Active
  Doc). `packages` — [[(назва файлу, bytes)], …]: кожен пакет — окремий звіт ДПС (головний
  документ і його додатки); у Об'єднаної з відокремленими підрозділами їх кілька;
* `source_ref` — запис, з якого надіслано (стан його подання видно на ньому самому);
* `record._aktiv_doc_report_changed(report)` — якщо запис має такий метод, ми кличемо його,
  щойно змінився стан звіту чи прийшли квитанції.

🔴 Повідомленню вікна «надіслано» на слово не віримо: воно лише просить сервер перепитати
Active Doc (`action_after_window`).
"""
import base64
import hashlib
import logging
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .aktiv_doc_client import AktivDocError
from .aktiv_doc_document import SYNC_PAGES, _parse_time

_logger = logging.getLogger(__name__)

STATES = [
    ("draft", "Не надіслано"),
    ("sent", "Надіслано до ДПС"),
    ("accepted", "Прийнято ДПС"),
    ("rejected", "Не прийнято ДПС"),
]


def package_sha(files):
    """Відбиток пакета — назви й вміст усіх файлів. Однаковий пакет не створює в кабінеті
    другу чернетку: видаляти звіти API не вміє, а кожне «Надіслати» плодило б їх."""
    digest = hashlib.sha256()
    for name, data in sorted(files):
        digest.update(name.upper().encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


class AktivDocReport(models.Model):
    _name = "aktiv.doc.report"
    _inherit = ["mail.thread"]
    _description = "Звіт до ДПС через Active Doc"
    _order = "id desc"
    _check_company_auto = True

    _sql_constraints = [
        ('adoc_uniq', "UNIQUE(company_id, adoc_id)", "Цей звіт Active Doc уже є в базі для цієї організації. Кожен звіт кабінету має в Odoo "
        "рівно один запис — інакше стани розійдуться. Відкрийте наявний запис у «Документообіг "
        "→ Звіти до ДПС»."),
    ]

    name = fields.Char("Звіт", required=True,
                       help="Що подається — назва звіту з програми, з якої його надіслано, або з "
                            "довідника форм ДПС.")
    company_id = fields.Many2one("res.company", string="Організація", required=True,
                                 default=lambda s: s.env.company, index=True,
                                 help="Платник, за якого подається звіт.")
    adoc_id = fields.Integer("Номер в Active Doc", readonly=True, copy=False, index=True,
                             help="Ідентифікатор звіту в кабінеті Active Doc.")
    form = fields.Char("Форма", readonly=True,
                       help="Код форми ДПС головного документа, напр. J0200126.")
    form_name = fields.Char("Назва форми", readonly=True,
                            help="Назва форми за довідником ДПС.")
    period_label = fields.Char("Період", readonly=True, help="Звітний період, як у кабінеті ДПС.")
    tin = fields.Char("Код платника", readonly=True,
                      help="ЄДРПОУ чи РНОКПП із шапки звіту — він мусить бути кодом організації "
                           "ключа Active Doc.")
    doc_stan = fields.Integer("Стан документа", readonly=True,
                              help="1 — звітний, 2 — новий звітний, 3 — уточнюючий.")
    state = fields.Selection(STATES, string="Стан", default="draft", required=True, readonly=True,
                             index=True,
                             help="Не надіслано → надіслано до ДПС (є номер) → прийнято "
                                  "(квитанція № 2 з реєстраційним номером) чи не прийнято.")
    state_label = fields.Char("Що зі звітом", readonly=True,
                              help="Стан словами від Active Doc.")
    dps_id = fields.Char("Номер у ДПС", readonly=True, copy=False, index=True,
                         help="Номер, який ДПС дала пакету у відповідь на подання.")
    dps_status = fields.Char("Відповідь ДПС", readonly=True, copy=False,
                             help="Код відповіді ДПС на подання: OK, ERROR_LINKED_DOCS, "
                                  "ERROR_XSD… — пояснення в полі нижче.")
    dps_text = fields.Char("Відповідь ДПС словами", readonly=True, copy=False,
                           help="Що відповіла ДПС на останню спробу надіслати.")
    sent_at = fields.Datetime("Надіслано", readonly=True, copy=False,
                              help="Коли ДПС прийняла пакет до обробки.")
    reg_number = fields.Char("Реєстраційний номер", readonly=True, copy=False,
                             help="Номер, під яким ДПС зареєструвала звіт (з квитанції № 2).")
    reg_date = fields.Datetime("Зареєстровано", readonly=True, copy=False,
                               help="Коли ДПС зареєструвала звіт.")
    reg_status = fields.Char("Стан у кабінеті ДПС", readonly=True, copy=False,
                             help="Як звіт значиться в Електронному кабінеті платника.")
    source_ref = fields.Reference(selection="_selection_source_model", string="Звіт в Odoo",
                                  readonly=True, index=True,
                                  help="Звіт, з якого надіслано (декларація, Об'єднана…). "
                                       "Натисніть, щоб відкрити.")
    batch = fields.Char("Подання", readonly=True, copy=False, index=True,
                        help="Службове: звіти, створені одним натисканням «Надіслати до ДПС» "
                             "(у Об'єднаної з відокремленими підрозділами — кілька пакетів).")
    package_sha = fields.Char("Відбиток пакета", readonly=True, copy=False, index=True,
                              help="Службове: контрольна сума файлів — той самий пакет не "
                                   "передається в Active Doc удруге.")
    file_ids = fields.Many2many("ir.attachment", string="Файли звіту", readonly=True, copy=False,
                                help="XML, які пішли в Active Doc: головний документ і додатки.")
    main_attachment_id = fields.Many2one("ir.attachment", string="Головний документ",
                                         readonly=True, copy=False,
                                         help="XML головного документа пакета.")
    files_info = fields.Text("Файли в Active Doc", readonly=True,
                             help="Які файли бачить кабінет Active Doc: назва для ДПС, форма, "
                                  "головний чи додаток.")
    receipt_ids = fields.One2many("aktiv.doc.report.receipt", "report_id", string="Квитанції",
                                  readonly=True,
                                  help="Квитанції ДПС: № 1 — на кожен файл після подання, № 2 — "
                                       "прийнято чи ні, з реєстраційним номером.")
    external_ref = fields.Char("Посилання на запис", readonly=True, copy=False,
                               help="Службове: база, модель і номер запису, з якого надіслано.")
    adoc_changed = fields.Datetime("Змінено", readonly=True,
                                   help="Коли звіт востаннє змінювався в Active Doc.")

    @api.model
    def _selection_source_model(self):
        return [(model.model, model.name) for model in self.env["ir.model"].sudo().search([])]

    def _client(self):
        return self.env["aktiv.doc.client"]

    def _source(self):
        self.ensure_one()
        record = self.source_ref
        return record.exists() if record else None

    # ------------------------------------------------------------------
    # Відповідь API → поля
    # ------------------------------------------------------------------
    @api.model
    def _vals_from_api(self, data):
        period = data.get("period") or {}
        files = data.get("files") or []
        vals = {
            "adoc_id": data.get("id"),
            "form": data.get("form") or False,
            "form_name": data.get("name") or False,
            "period_label": period.get("label") or False,
            "tin": data.get("tin") or False,
            "doc_stan": data.get("doc_stan") or 0,
            "state_label": data.get("state_label") or False,
            "dps_id": data.get("dps_id") or False,
            "dps_status": data.get("dps_status") or False,
            "dps_text": data.get("dps_text") or False,
            "sent_at": _parse_time(data.get("sent")),
            "reg_number": data.get("reg_number") or False,
            "reg_date": _parse_time(data.get("reg_date")),
            "reg_status": data.get("reg_status") or False,
            "external_ref": data.get("external_ref") or False,
            "adoc_changed": _parse_time(data.get("changed")),
            "files_info": "\n".join("%s%s — %s" % (
                f.get("file_name") or "?", _(" (головний)") if f.get("main") else "",
                f.get("name") or f.get("form") or "") for f in files) or False,
        }
        if data.get("state") in dict(STATES):
            vals["state"] = data["state"]
        return vals

    def _apply_api(self, data):
        """Записати відповідь API у звіт; змінився стан чи прийшли квитанції — сказати про це
        й запису, з якого звіт надіслано."""
        self.ensure_one()
        before = (self.state, self.state_label, self.reg_number,
                  len(self.receipt_ids.filtered("xml_attachment_id")))
        self.write(self._vals_from_api(data))
        self._apply_receipts(data.get("receipts") or [])
        after = (self.state, self.state_label, self.reg_number,
                 len(self.receipt_ids.filtered("xml_attachment_id")))
        if after != before:
            if after[:2] != before[:2]:
                self._post_event(self.state_label or dict(STATES)[self.state])
            self._notify_source()
        return True

    def _apply_receipts(self, receipts):
        """Квитанції з відповіді API — у записи; файли — для тих, що вже розшифровані."""
        Receipt = self.env["aktiv.doc.report.receipt"]
        for item in receipts:
            rid = item.get("id")
            if not rid:
                continue
            receipt = self.receipt_ids.filtered(lambda r: r.adoc_receipt_id == rid)[:1]
            vals = {
                "adoc_receipt_id": rid,
                "kind": item.get("kind") or False,
                "num": item.get("num") or 0,
                "name": item.get("name") or _("Квитанція"),
                "file_name": item.get("file_name") or False,
                "result": item.get("result") or False,
                "reg_number": item.get("reg_number") or False,
                "received": _parse_time(item.get("received")),
                "signed_ok": bool(item.get("signed_ok")),
                "encrypted": bool(item.get("encrypted")),
                "files": ",".join(item.get("files") or []) or False,
            }
            if receipt:
                receipt.write(vals)
            else:
                receipt = Receipt.create(dict(vals, report_id=self.id))
            receipt._fetch_files()

    def _notify_source(self):
        """Запис, з якого надіслано звіт, дізнається про зміну (якщо вміє її прийняти)."""
        for report in self:
            source = report._source()
            if source and hasattr(source, "_aktiv_doc_report_changed"):
                source._aktiv_doc_report_changed(report)

    def _post_event(self, body):
        """Подія — у стрічку звіту й у стрічку запису, з якого його надіслано."""
        for report in self:
            report.message_post(body=body)
            source = report._source()
            if source and hasattr(source, "message_post"):
                source.message_post(body=_("Active Doc, «%(report)s»: %(event)s",
                                           report=report.name, event=body))

    def _attach(self, content, name, mimetype):
        return self.env["ir.attachment"].sudo().create({
            "name": name, "raw": content, "mimetype": mimetype,
            "res_model": self._name, "res_id": self.id, "company_id": self.company_id.id,
        })

    # ------------------------------------------------------------------
    # Створення з запису (кнопка «Надіслати до ДПС» в іншому модулі)
    # ------------------------------------------------------------------
    @api.model
    def _reports_problems(self, company):
        """Чи може організація подавати звіти через Active Doc — `GET me` → `org.reports`."""
        me = self._client()._request(company, "GET", "me")
        enabled = bool((me.get("org") or {}).get("reports"))
        if company.sudo().aktiv_doc_reports != enabled:
            company.sudo().aktiv_doc_reports = enabled
        if not enabled:
            raise AktivDocError(_(
                "Звітність до ДПС для організації «%(company)s» в Active Doc ще не ввімкнено.\n\n"
                "Чому: подання звітів через Active Doc — пілот, його вмикають організації на "
                "прохання.\n"
                "Що зробити: напишіть на info@aktiv.in.ua — увімкнемо. До того звіт можна "
                "подати в Електронному кабінеті ДПС: вивантажте XML кнопкою у звіті.",
                company=company.name), code="EDPS_OFF")
        return True

    @api.model
    def _aktiv_doc_submit(self, record, packages, title):
        """Пакети звіту → звіти Active Doc (чернетки) → вікно, де людина надсилає перший."""
        company = record.company_id if "company_id" in record._fields and record.company_id \
            else self.env.company
        if not company.aktiv_doc_enabled:
            raise AktivDocError(_(
                "Active Doc не підключено для організації «%(company)s».\n\n"
                "Чому: без ключа API Odoo не може передати звіт в Active Doc.\n"
                "Що зробити: адміністратор створює ключ у кабінеті Active Doc («Організація» → "
                "«Ключі API») і вставляє його в Налаштуваннях: Виставлення рахунків → Active "
                "Doc.", company=company.name), code="ENOKEY")
        self._reports_problems(company)
        ref = "%s,%s" % (record._name, record.id)
        database = self.env["ir.config_parameter"].sudo().get_param("database.uuid")
        batch = uuid.uuid4().hex
        reports = self.browse()
        for number, files in enumerate(packages, 1):
            sha = package_sha(files)
            # Той самий пакет, ще не надісланий, — та сама чернетка в кабінеті.
            draft = self.search([("company_id", "=", company.id), ("source_ref", "=", ref),
                                 ("package_sha", "=", sha), ("state", "=", "draft")], limit=1)
            if draft:
                draft.batch = batch
                reports |= draft
                continue
            name = title if len(packages) == 1 else _(
                "%(title)s — пакет %(n)d з %(total)d", title=title, n=number, total=len(packages))
            data = self._client()._request(company, "POST", "reports", payload={
                "files": [{"file_name": file_name, "file": base64.b64encode(raw).decode("ascii")}
                          for file_name, raw in files],
                "external_ref": "%s·%s·%s" % (database, record._name, record.id),
            })
            vals = self._vals_from_api(data)
            vals.update({"company_id": company.id, "name": name, "source_ref": ref,
                         "batch": batch, "package_sha": sha})
            report = self.create(vals)
            main_name = next((f.get("file_name") for f in data.get("files") or [] if f.get("main")),
                             files[0][0])
            attachments = self.env["ir.attachment"]
            for file_name, raw in files:
                attachments |= report._attach(raw, file_name, "application/xml")
            report.write({
                "file_ids": [(6, 0, attachments.ids)],
                "main_attachment_id": (attachments.filtered(
                    lambda a: a.name.upper() == (main_name or "").upper())[:1] or attachments[:1]).id,
            })
            report._post_event(_("звіт передано в Active Doc, файлів: %d", len(files)))
            reports |= report
        first = reports.filtered(lambda r: r.state == "draft")[:1]
        if not first:
            raise UserError(_(
                "Ці файли вже надіслано до ДПС через Active Doc.\n\n"
                "Що зробити: відкрийте подання (кнопка «Відкрити» над звітом) — там номер у ДПС і "
                "квитанції."))
        return first.action_send_window()

    # ------------------------------------------------------------------
    # Вікно звітності
    # ------------------------------------------------------------------
    def _window(self, expected):
        """Вікно Active Doc для звіту: `send` — надіслати чернетку, `receipts` — квитанції."""
        self.ensure_one()
        session = self._client()._request(self.company_id, "POST",
                                          "reports/%d/sign_session" % self.adoc_id, payload={})
        mode = session.get("mode") or expected
        return {
            "type": "ir.actions.client",
            "tag": "aktiv_doc_sign",
            "params": {
                "url": session.get("url"),
                "origin": self._client()._origin(self.company_id),
                "allowed_origin": session.get("origin") or "",
                "adoc_id": self.adoc_id,
                "doc_id": self.id,
                "refresh_model": self._name,
                "refresh_method": "action_after_window",
                # Чого чекати від вікна: «надіслано» чи «квитанції оновлено» (контракт).
                "message_types": ["adoc:reported"] if mode == "send" else ["adoc:report_updated"],
                "busy_text": _("Готово — оновлюю стан звіту…"),
                "title": (_("Подання до ДПС: %s") if mode == "send"
                          else _("Квитанції ДПС: %s")) % self.name,
            },
        }

    def action_send_window(self):
        """«Надіслати до ДПС» — вікно Active Doc: ключ, «Я перевірив…», підпис і надсилання."""
        self.ensure_one()
        self.action_refresh()
        if self.state != "draft":
            raise UserError(_(
                "«%(report)s» уже надіслано до ДПС (%(state)s).\n\n"
                "Що зробити: квитанції — кнопкою «Квитанції»; виправлення подається новим "
                "звітом (уточнюючим чи новим звітним).",
                report=self.name, state=self.state_label or dict(STATES)[self.state]))
        return self._window("send")

    def action_receipts_window(self):
        """«Квитанції» — вікно Active Doc: отримати квитанцію № 2 з кабінету ДПС своїм ключем."""
        self.ensure_one()
        self.action_refresh()
        if self.state == "draft":
            raise UserError(_(
                "«%s» ще не надіслано до ДПС — квитанцій немає.\n\n"
                "Що зробити: натисніть «Надіслати до ДПС».", self.name))
        return self._window("receipts")

    def action_after_window(self):
        """Вікно сказало «готово» (або його закрили) — перепитати Active Doc. Якщо цим самим
        натисканням створено ще пакети й вони не надіслані (Об'єднана з підрозділами) —
        одразу вікно наступного."""
        self.ensure_one()
        self.action_refresh()
        if self.state != "draft" and self.batch:
            following = self.search([("batch", "=", self.batch), ("state", "=", "draft"),
                                     ("id", "!=", self.id)], order="id", limit=1)
            if following:
                action = following.action_send_window()
                action["params"]["reload"] = True
                return action
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------
    def action_refresh(self):
        """«Оновити» — перепитати Active Doc про стан і квитанції."""
        for report in self.filtered("adoc_id"):
            data = report._client()._request(report.company_id, "GET",
                                             "reports/%d" % report.adoc_id)
            report._apply_api(data)
        return True

    def action_open_source(self):
        self.ensure_one()
        record = self._source()
        if not record:
            raise UserError(_(
                "Звіту в Odoo для «%s» немає.\n\n"
                "Чому: звіт завантажено в кабінеті Active Doc, а не надіслано з Odoo, або запис "
                "видалено.\n"
                "Що зробити: файли звіту — у вкладці «Файли».", self.name))
        return {"type": "ir.actions.act_window", "res_model": record._name,
                "res_id": record.id, "view_mode": "form", "target": "current"}

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        sent = self.filtered(lambda r: r.state != "draft")
        if sent:
            raise UserError(_(
                "Звіт, надісланий до ДПС, видалити не можна: %(names)s.\n\n"
                "Чому: це запис про подання, а квитанції — доказ подання.\n"
                "Що зробити: залиште запис; виправлення подається новим звітом.",
                names=", ".join(sent.mapped("name"))))

    # ------------------------------------------------------------------
    # Синхронізація: звіти, надіслані з кабінету, і зміни стану
    # ------------------------------------------------------------------
    @api.model
    def action_sync_now(self):
        """«Оновити зараз» на списку — те саме, що робить cron, для поточної організації."""
        self._sync_company(self.env.company)
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    @api.model
    def _cron_sync(self):
        # Лише організації, де «Звітність до ДПС» увімкнено: інакше кабінет відповідав би
        # відмовою на кожен прогін.
        companies = self.env["res.company"].sudo().search([("aktiv_doc_reports", "=", True)])
        for company in companies.filtered("aktiv_doc_key"):
            try:
                self.with_company(company)._sync_company(company)
            except AktivDocError as error:
                _logger.warning("Active Doc: звіти організації %s не синхронізовано (%s)",
                                company.id, error.code or error.status)
                if error.code == "EDPS_OFF":
                    company.aktiv_doc_reports = False

    @api.model
    def _sync_company(self, company):
        if not company.sudo().aktiv_doc_key:
            raise UserError(_(
                "Active Doc не підключено для організації «%s».\n\n"
                "Що зробити: вставте ключ API в Налаштуваннях: Виставлення рахунків → "
                "Active Doc.", company.name))
        cursor = company.sudo().aktiv_doc_report_cursor
        for _page in range(SYNC_PAGES):
            data = self._client()._request(company, "GET", "reports",
                                           params={"changed_since": cursor} if cursor else None)
            for item in data.get("reports") or []:
                self._upsert_from_api(company, item)
            cursor = data.get("next") or cursor
            if not data.get("more"):
                break
        company.sudo().aktiv_doc_report_cursor = cursor
        return True

    @api.model
    def _upsert_from_api(self, company, data):
        report = self.search([("company_id", "=", company.id), ("adoc_id", "=", data.get("id"))],
                             limit=1)
        if report:
            report._apply_api(data)
            return report
        # Звіт, завантажений у кабінеті (не з Odoo), — теж тут: подання організації в одному
        # місці. Запис Odoo — лише якщо звіт надіслано з ЦІЄЇ бази.
        vals = self._vals_from_api(data)
        vals.update({"company_id": company.id,
                     "name": data.get("name") or data.get("form") or _("Звіт %s", data.get("id"))})
        record = self.env["aktiv.doc.document"]._record_from_ref(vals.get("external_ref"))
        if record:
            vals["source_ref"] = "%s,%s" % (record._name, record.id)
        report = self.create(vals)
        report._apply_receipts(data.get("receipts") or [])
        report._notify_source()
        return report


class AktivDocReportReceipt(models.Model):
    _name = "aktiv.doc.report.receipt"
    _description = "Квитанція ДПС до звіту Active Doc"
    _order = "num, id"

    report_id = fields.Many2one("aktiv.doc.report", string="Звіт", required=True,
                                ondelete="cascade", index=True,
                                help="Звіт, до якого квитанція.")
    company_id = fields.Many2one(related="report_id.company_id", store=True, index=True,
                                 help="Організація звіту.")
    adoc_receipt_id = fields.Integer("Номер в Active Doc", readonly=True, index=True,
                                     help="Ідентифікатор квитанції в кабінеті Active Doc.")
    kind = fields.Char("Вид", readonly=True,
                       help="kvt — квитанція ДПС; doc — копія звіту з кабінету ДПС.")
    num = fields.Integer("№", readonly=True,
                         help="1 — ДПС отримала файл; 2 — прийняла чи ні, з реєстраційним "
                              "номером.")
    name = fields.Char("Квитанція", readonly=True, help="Назва квитанції.")
    file_name = fields.Char("До файлу", readonly=True,
                            help="Файл пакета, до якого квитанція (у звіту з додатками № 1 — до "
                                 "кожного файлу).")
    result = fields.Char("Результат", readonly=True,
                         help="Що написала ДПС: «Документ збережено…», «Не прийнято…».")
    reg_number = fields.Char("Реєстраційний номер", readonly=True,
                             help="Номер реєстрації звіту в ДПС (у квитанції № 2).")
    received = fields.Datetime("Отримано", readonly=True, help="Коли квитанція надійшла.")
    signed_ok = fields.Boolean("Підпис ДПС перевірено", readonly=True,
                               help="Кабінет Active Doc перевірив підпис ДПС на квитанції.")
    encrypted = fields.Boolean("Ще зашифрована", readonly=True,
                               help="Квитанцію ДПС зашифрувала на ваш ключ: відкрийте «Квитанції» "
                                    "й укажіть ключ — вона розшифрується.")
    files = fields.Char("Файли в Active Doc", readonly=True,
                        help="Службове: які файли квитанції віддає кабінет (xml, pdf…).")
    xml_attachment_id = fields.Many2one("ir.attachment", string="XML квитанції", readonly=True,
                                        help="Квитанція у форматі ДПС.")
    pdf_attachment_id = fields.Many2one("ir.attachment", string="PDF", readonly=True,
                                        help="Квитанція чи копія звіту від ДПС — для друку.")

    def _download(self, attachment):
        self.ensure_one()
        if not attachment:
            raise UserError(_(
                "Файлу квитанції ще немає.\n\n"
                "Чому: квитанцію ДПС шифрує на ключ вашої організації, і кабінет віддає її лише "
                "розшифрованою.\n"
                "Що зробити: відкрийте звіт і натисніть «Квитанції» — у вікні Active Doc вкажіть "
                "ключ."))
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/web/content/%d?download=true" % attachment.id}

    def action_download_xml(self):
        return self._download(self.xml_attachment_id)

    def action_download_pdf(self):
        return self._download(self.pdf_attachment_id)

    def _fetch_files(self):
        """Файли розшифрованої квитанції — у базу (поки зашифрована, кабінет їх не віддасть)."""
        for receipt in self.filtered(lambda r: not r.encrypted and r.adoc_receipt_id):
            available = (receipt.files or "").split(",")
            report = receipt.report_id
            for what, field, mimetype, ext in (("xml", "xml_attachment_id", "application/xml", "xml"),
                                               ("pdf", "pdf_attachment_id", "application/pdf", "pdf")):
                if what not in available or receipt[field]:
                    continue
                try:
                    content = report._client()._request(
                        report.company_id, "GET", "reports/%d/receipts/%d/%s" % (
                            report.adoc_id, receipt.adoc_receipt_id, what), raw=True)
                except AktivDocError as error:
                    _logger.info("Active Doc: файл квитанції %s не отримано (%s)",
                                 receipt.adoc_receipt_id, error.code or error.status)
                    continue
                name = "%s — %s.%s" % (receipt.name or _("Квитанція"), report.name, ext)
                receipt[field] = report._attach(content, name, mimetype)
