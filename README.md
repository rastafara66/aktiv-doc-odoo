# Active Doc for Odoo — KEP e-signature and document exchange

Sign invoices, acts and delivery notes with a Ukrainian qualified electronic
signature (KEP) and send them to counterparties through
[Active Doc](https://doc.aktiv.in.ua) — without leaving Odoo. Incoming documents
appear by themselves; once both sides have signed, the archive (document, every
signature, verification protocol) is attached to the invoice.

* Module: `aktiv_doc`, branch per Odoo series (`19.0`).
* Depends on `account` and `mail` only. License: LGPL-3. Free.
* Author: 3A Studio — <https://3a-studio.aktiv.in.ua>, support: info@aktiv.in.ua.

## Українською

Рахунки, акти й накладні підписуються КЕП і йдуть контрагенту через
[Active Doc](https://doc.aktiv.in.ua) прямо з Odoo; вхідні з'являються самі;
підписаний обома сторонами архів прикріплюється до рахунку. Безкоштовно, LGPL-3.

## Development

* Tests: `--test-tags /aktiv_doc` (the network is stubbed, no keys needed).
* End-to-end against the live service: `python tools/e2e_aktiv_doc.py` — needs
  test organisation keys in a local, git-ignored `e2e.local/`.
* Store images and description: `tools/make_icon.py`, `tools/make_banner.py`,
  `tools/make_description.py`.
