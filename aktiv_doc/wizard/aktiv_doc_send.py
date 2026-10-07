# -*- coding: utf-8 -*-
"""«Надіслати на підпис»: друкована форма, отримувач, перегляд — і одразу вікно підпису."""
import base64
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.aktiv_doc_document import CODE_RE, format_problems

#: Типова друкована форма для моделі — найзвичніша, якщо їх кілька.
DEFAULT_REPORTS = {"account.move": "account.account_invoices"}


class AktivDocSend(models.TransientModel):
    _name = "aktiv.doc.send"
    _description = "Надіслати на підпис через Active Doc"

    res_model = fields.Char("Модель запису", required=True, readonly=True,
                            help="Службове: якого виду запис надсилаємо.")
    res_id = fields.Integer("Номер запису", required=True, readonly=True,
                            help="Службове: який саме запис надсилаємо.")
    record_name = fields.Char("Документ обліку", compute="_compute_record_name",
                              help="Запис, з якого береться друкована форма.")
    report_id = fields.Many2one(
        "ir.actions.report", string="Друкована форма", required=True,
        domain="[('model', '=', res_model), ('report_type', '=', 'qweb-pdf')]",
        help="Яку саме друковану форму запису підписують. PDF формується тут же, у "
             "тому вигляді, як його друкує Odoo.")
    doc_name = fields.Char("Назва для контрагента", required=True,
                           help="Як документ зватиметься в Active Doc і в листі контрагенту.")
    partner_id = fields.Many2one("res.partner", string="Контрагент",
                                 help="Кому надсилаємо. Код і пошта підставляються з картки.")
    recipient_code = fields.Char("ЄДРПОУ / РНОКПП отримувача",
                                 help="За цим кодом Active Doc шукає кабінет контрагента: є — "
                                      "документ ляже в його вхідні; немає — він отримає "
                                      "посилання й підпише без реєстрації.")
    recipient_name = fields.Char("Назва отримувача",
                                 help="Як отримувач підписаний у документі й у листі.")
    recipient_email = fields.Char("Пошта отримувача",
                                  help="Сюди Active Doc надішле лист із посиланням, якщо в "
                                       "контрагента немає кабінету. Без пошти посилання "
                                       "доведеться передати самим.")
    preview_pdf = fields.Binary("Перегляд", readonly=True,
                                help="Сформований PDF — саме його буде підписано.")
    preview_name = fields.Char("Файл", readonly=True, help="Ім'я файлу, що піде в Active Doc.")

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        model = vals.get("res_model") or self.env.context.get("default_res_model")
        res_id = vals.get("res_id") or self.env.context.get("default_res_id")
        if not model or not res_id or model not in self.env:
            return vals
        record = self.env[model].browse(res_id).exists()
        if not record:
            return vals
        vals.setdefault("doc_name", record.display_name)
        report = self._default_report(model)
        if report:
            vals.setdefault("report_id", report.id)
        partner = record._aktiv_doc_partner() if hasattr(record, "_aktiv_doc_partner") \
            else self.env["res.partner"]
        if partner:
            vals.setdefault("partner_id", partner.id)
            vals.update({key: value for key, value in self._recipient_of(partner).items()
                         if not vals.get(key)})
        return vals

    @api.model
    def _default_report(self, model):
        xmlid = DEFAULT_REPORTS.get(model)
        report = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else None
        if report and report.report_type == "qweb-pdf":
            return report
        return self.env["ir.actions.report"].search(
            [("model", "=", model), ("report_type", "=", "qweb-pdf")], limit=1)

    @api.model
    def _recipient_of(self, partner):
        # ЄДРПОУ у базах буває або в «Реєстрі компанії», або в «Довідці» — беремо
        # заповнене; РНОКПП фізособи — часто в податковому номері.
        code = next((value.strip() for value in (partner.company_registry, partner.ref, partner.vat)
                     if value and CODE_RE.match(value.strip())), "")
        return {"recipient_code": code, "recipient_name": partner.name or "",
                "recipient_email": partner.email or ""}

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            self.update(self._recipient_of(self.partner_id.commercial_partner_id))

    @api.onchange("report_id")
    def _onchange_report_id(self):
        self.preview_pdf = False

    @api.depends("res_model", "res_id")
    def _compute_record_name(self):
        for wizard in self:
            record = wizard._record()
            wizard.record_name = record.display_name if record else False

    def _record(self):
        self.ensure_one()
        if not self.res_model or self.res_model not in self.env or not self.res_id:
            return None
        return self.env[self.res_model].browse(self.res_id).exists() or None

    # ------------------------------------------------------------------
    def _problems(self):
        """Усе, що завадить надіслати, — одним списком (§9)."""
        self.ensure_one()
        problems = []
        record = self._record()
        if not record:
            return [(_("Запису обліку більше немає"),
                     _("його видалили, поки відкрито це вікно"),
                     _("закрийте вікно й відкрийте документ заново"))]
        company = record._aktiv_doc_company()
        if not company.aktiv_doc_enabled:
            problems.append((
                _("Active Doc не підключено для організації «%s»", company.name),
                _("без ключа API модуль не може звернутися до Active Doc"),
                _("адміністратор створює ключ у кабінеті Active Doc («Організація» → "
                  "«Ключі API») і вставляє його в Налаштуваннях: Виставлення рахунків → "
                  "Active Doc")))
        problems += record._aktiv_doc_problems()
        if not self.report_id:
            problems.append((_("Не вибрано друковану форму"),
                             _("підписують конкретний PDF"),
                             _("виберіть форму в полі «Друкована форма»")))
        code = (self.recipient_code or "").strip()
        if not code:
            problems.append((_("Не вказано ЄДРПОУ / РНОКПП отримувача"),
                             _("за цим кодом Active Doc знаходить кабінет контрагента"),
                             _("впишіть код тут або в картку контрагента (поле «Реєстр "
                               "компанії»)")))
        elif not CODE_RE.match(code):
            problems.append((_("«%s» — не ЄДРПОУ і не РНОКПП", code),
                             _("ЄДРПОУ має 8 цифр, РНОКПП — 10"),
                             _("виправте код")))
        if not (self.recipient_name or "").strip():
            problems.append((_("Не вказано назву отримувача"),
                             _("вона стоїть у документі й у листі контрагенту"),
                             _("впишіть назву або виберіть контрагента")))
        return problems

    def _file_name(self):
        base = re.sub(r"[^\w\-]+", "_", self.doc_name or "document", flags=re.UNICODE).strip("_")
        return "%s.pdf" % (base[:80] or "document")

    def _render_pdf(self):
        record = self._record()
        try:
            pdf, _kind = self.env["ir.actions.report"]._render_qweb_pdf(
                self.report_id.report_name, [record.id])
        except UserError:
            raise
        except Exception as error:  # noqa: BLE001 - рушій PDF буває не встановлений
            raise UserError(_(
                "PDF «%(report)s» не сформувався.\n\n"
                "Чому: %(kind)s — найчастіше на сервері немає wkhtmltopdf або друкована "
                "форма має помилку.\n"
                "Що зробити: перевірте, чи ця форма друкується звичайною кнопкою «Друк»; "
                "якщо ні — зверніться до адміністратора.",
                report=self.report_id.name, kind=type(error).__name__)) from None
        return pdf

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new", "name": _("Надіслати на підпис")}

    def action_preview(self):
        """«Переглянути» — сформувати PDF тут же, нічого не надсилаючи."""
        self.ensure_one()
        if not self.report_id or not self._record():
            raise UserError(format_problems(self.env, _("Переглянути не вийде."),
                                            self._problems()))
        self.write({"preview_pdf": base64.b64encode(self._render_pdf()),
                    "preview_name": self._file_name()})
        return self._reopen()

    def action_check(self):
        """«Перевірити» — нічого не створює, лише звітує (§9)."""
        self.ensure_one()
        problems = self._problems()
        if problems:
            raise UserError(format_problems(self.env, _("Надіслати на підпис поки не вийде."),
                                            problems))
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Проблем немає"), "type": "success", "sticky": False,
            "message": _("Перевірено: Active Doc підключено, запис готовий до підпису, вибрано "
                         "друковану форму, код отримувача %(code)s має правильний вигляд.",
                         code=self.recipient_code.strip())}}

    def action_create(self):
        """«Підписати» — документ в Active Doc і одразу вікно підпису КЕП."""
        self.ensure_one()
        problems = self._problems()
        if problems:
            raise UserError(format_problems(self.env, _("Документ не створено."), problems))
        record = self._record()
        pdf = base64.b64decode(self.preview_pdf) if self.preview_pdf else self._render_pdf()
        doc = self.env["aktiv.doc.document"]._create_from_record(
            record, pdf, self._file_name(), self.doc_name.strip(),
            self.partner_id.commercial_partner_id if self.partner_id else None,
            self.recipient_code.strip(), self.recipient_name.strip(),
            (self.recipient_email or "").strip())
        action = doc.action_sign()
        # Під вікном підпису — картка документа: після підпису там «Надіслати».
        action["params"]["doc_action"] = {
            "type": "ir.actions.act_window", "res_model": doc._name, "res_id": doc.id,
            "views": [[False, "form"]], "target": "current"}
        return action
