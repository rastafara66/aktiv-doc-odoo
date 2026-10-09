# -*- coding: utf-8 -*-
"""Відмінності серій Odoo — за тим, що в базі Є, а не за номером серії.

Той самий код іде в 18.0, 19.0 і 20.0 (інші гілки — злиття 19.0), тож кожну відмінність
вирішує наявність поля: номер серії бреше, щойно Odoo щось переносить між версіями, а
поле або є, або його немає.
"""
import base64

#: Поля контакта, де буває код отримувача — ЄДРПОУ чи РНОКПП, — у порядку перебору.
#: Odoo 18/19 тримають ЄДРПОУ в `company_registry`; в Odoo 20 цього поля немає взагалі,
#: код — у `vat`.
PARTNER_CODE_FIELDS = ("company_registry", "ref", "vat")
#: Як поле з ЄДРПОУ підписане в картці контакта (для підказок).
REGISTRY_LABELS = {"company_registry": "Реєстр компанії", "vat": "Податковий номер"}


def partner_code_fields(env):
    """Ті з `PARTNER_CODE_FIELDS`, що є в цій базі."""
    partner_fields = env["res.partner"]._fields
    return [name for name in PARTNER_CODE_FIELDS if name in partner_fields]


def registry_field(env):
    """Поле контакта для ЄДРПОУ: `company_registry` (Odoo 18/19), `vat` (Odoo 20)."""
    return "company_registry" if "company_registry" in env["res.partner"]._fields else "vat"


def registry_label(env):
    """Підпис `registry_field()` у картці контакта — так його називають підказки."""
    return REGISTRY_LABELS[registry_field(env)]


def binary_content(value):
    """Сирі байти значення `fields.Binary`, b'' — якщо порожнє.

    Odoo 18/19 віддають base64 (bytes чи str), Odoo 20 — `BinaryValue`, у якого
    `.content` — уже сирі байти: розкодувати їх ще раз як base64 означало б тихо
    отримати сміття. Запис — дзеркально: `bytes` Odoo 20 не приймає («use BinaryValue
    instead of bytes»), тож пишемо base64 *рядком* — його читає кожна серія.
    """
    if not value:
        return b""
    content = getattr(value, "content", None)
    if content is not None:
        return content
    return base64.b64decode(value)


def attachment_content(attachment):
    """Сирі байти `ir.attachment`, b'' — якщо порожнє.

    `raw` є в кожній серії (`datas` в Odoo 20 прибрано): в Odoo 18/19 — байти, в
    Odoo 20 — `BinaryValue`.
    """
    raw = attachment.raw
    if not raw:
        return b""
    content = getattr(raw, "content", None)
    return raw if content is None else content
