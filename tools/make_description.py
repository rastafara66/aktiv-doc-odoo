# -*- coding: utf-8 -*-
"""Опис для магазину (`aktiv_doc/static/description/index.html`).

    python tools/make_description.py

Шаблон родини (як `yellow-edr-connector/tools/make_description.py`): перемикач
«English · Українською», широкий банер (3A `tools/store/make_wide_banner.py`),
англійська половина, українська половина. Версія й адреса підтримки — з
маніфесту. Файл — чистий ASCII: магазин віддає опис без charset, тож решта
символів іде числовими сутностями. Жодного `<style>`/`<script>`: санітайзер
магазину на них знищує весь опис.

🔴 Умови Active Doc (тарифи, які ключі підходять) — з живого doc.aktiv.in.ua і з
самого вікна підпису, звірено 07.10.2026: файлові ключі (Key-6.dat, *.jks, *.pfx) — у
вікні; токен, хмарний ключ, Дія.Підпис — підписом на czo.gov.ua і завантаженням файлу
підпису в те саме вікно. Змінились там — змінити тут.
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = "aktiv_doc"
ACCENT = "#4b3c8f"
CATALOG = "https://apps.odoo.com/apps/modules/browse?author=3A%20Studio"
SITE = "https://3a-studio.aktiv.in.ua"
ADOC = "https://doc.aktiv.in.ua"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
MONTHS_UK = ["січень", "лютий", "березень", "квітень", "травень", "червень", "липень",
             "серпень", "вересень", "жовтень", "листопад", "грудень"]

#: Що нового, новіше першим: (версія без серії, місяць, рік, англійською, українською).
#: Сухо (§3). Серію дописує `news()` з маніфесту, тож у гілках 18.0 і 19.0 файл однаковий.
#: Діапазон білдів — «1.0.0 – 1.0.2» (білд лише опису запису не додає, §3).
NEWS = [
    ("1.0.0 – 1.0.2", "October", 2026,
     "First release: send for signature from invoices, signing inside Odoo, incoming "
     "documents, the signed archive on the invoice, an Active Doc column in the invoice "
     "list, update check.",
     "Перша версія: надсилання на підпис із рахунків, підпис усередині Odoo, вхідні "
     "документи, підписаний архів у рахунку, колонка «Active Doc» у списку рахунків, "
     "перевірка версій."),
]

FAMILY_EN = [
    ("Aktiv", "Ukrainian accounting and tax reporting inside Odoo: turnover sheet, VAT "
              "return, balance sheet, payroll, fixed assets"),
    ("Data Exchange", "orders and documents between Odoo and 1C / BAS through files"),
    ("Bank Sync", "bank statements straight into your journals, with the partner code "
                  "on every line"),
    ("Partner Autofill", "fill a partner card by its EDRPOU code"),
    ("3A-dealer", "car dealerships, service and parts"),
    ("Rakhivnyk", "reporting for sole traders on the simplified tax"),
]
FAMILY_UK = [
    ("Актив", "бухгалтерський облік і податкова звітність України в Odoo: ОСВ, декларація "
              "з ПДВ, баланс, зарплата, основні засоби"),
    ("Data Exchange", "обмін замовленнями й документами між Odoo і 1С / BAS через файли"),
    ("Bank Sync", "банківські виписки одразу в журнали, з кодом контрагента в кожному рядку"),
    ("Partner Autofill", "картка контрагента за кодом ЄДРПОУ"),
    ("3A-dealer", "автосалон, сервіс і запчастини"),
    ("Рахівник", "звітність ФОП на спрощеній системі"),
]

#: Умови перед встановленням — жирним на блідо-жовтому тлі з жовтим «⚠️» (власник 07.10.2026).
#: Лише прості властивості `style=` (background, border, padding, color): решту санітайзер
#: магазину мовчки зрізає.
WARNING_BOX = ('<div style="background:#fff8d6;border:1px solid #f2c94c;border-left:6px solid '
               '#f2c94c;border-radius:8px;padding:14px 18px;color:#5c4400;">\n'
               '        <p><b><span style="font-size:22px;">&#9888;&#65039;</span> %s</b></p>\n'
               '        <ul>\n%s        </ul>\n      </div>')
WARN_EN = ("Before you install", [
    "<b>Odoo must open over <u>https</u>. On an http page the browser switches off the "
    "cryptography the signing window needs, and a real organisation's key is bound to an "
    "https address only.</b>",
    "<b>Odoo Online does not install third-party modules</b> &mdash; use Odoo.sh or your own "
    "server.",
    "<b>You need an organisation cabinet on <a href=\"%(adoc)s\" style=\"color:#5c4400;\">"
    "doc.aktiv.in.ua</a></b> &mdash; created with one signature of your key; the free plan "
    "is enough to start.",
])
WARN_UK = ("Перш ніж встановлювати", [
    "<b>Odoo мусить відкриватися за <u>https</u>. На http-сторінці браузер вимикає "
    "криптографію, потрібну вікну підпису, а ключ справжньої організації прив'язується лише до "
    "https-адреси.</b>",
    "<b>Odoo Online сторонніх модулів не встановлює</b> — потрібен Odoo.sh або власний сервер.",
    "<b>Потрібен кабінет організації на <a href=\"%(adoc)s\" style=\"color:#5c4400;\">"
    "doc.aktiv.in.ua</a></b> — створюється одним підписом вашого ключа; для початку досить "
    "безкоштовного тарифу.",
])

EN = {
    "anchor": "descr-en",
    "title": "Sign invoices with KEP and send them &mdash; without leaving Odoo",
    "subtitle": "Qualified electronic signature and document exchange with your "
                "counterparties, through the Active Doc service",
    "meta": "Version %(version)s &middot; LGPL-3 &middot; free &middot; Odoo %(odoo)s",
    "blocks": [
        ("", "WARNING"),
        ("If you came from 1C / BAS",
         "<p>In 1C and BAS the invoice is made in one program and signed in another &mdash; "
         "M.E.Doc or a separate e-document service &mdash; and the signed copy has to be "
         "found and filed back by hand. Here the button is on the invoice itself, the "
         "signing window opens inside Odoo, and the signed archive comes back to the "
         "same invoice.</p>"),
        (("What it does", [
            "<b>Send for signature</b> &mdash; on a posted invoice, act or delivery note: "
            "pick the printed form, the recipient comes from the partner card, preview the PDF",
            "<b>Sign inside Odoo</b> &mdash; the Active Doc signing window opens in a dialog; "
            "no separate cabinet to log into",
            "<b>Send</b> &mdash; to the counterparty's Active Doc cabinet by EDRPOU / RNOKPP, "
            "or as a link by e-mail; they sign without registering",
            "<b>Incoming</b> &mdash; documents sent to your code appear by themselves; sign "
            "them, or reject with a reason the sender will see",
            "<b>Signed archive</b> &mdash; once both sides have signed, the document, every "
            "signature and the verification protocol are attached to the invoice",
        ]), ("How it is built", [
            "<b>Your key never reaches Odoo</b> &mdash; the key file and its password stay in "
            "the signing window; Odoo only learns that the document was signed",
            "<b>The API key stays on the server</b> &mdash; never in the browser, never in "
            "the logs; document contents are not logged either",
            "<b>&ldquo;Signed&rdquo; is not taken on trust</b> &mdash; the message from the "
            "window is checked for its origin, and the state is re-read from Active Doc",
            "<b>Every problem at once</b> &mdash; before sending, the wizard lists everything "
            "that would block it, each with what to do",
            "<b>Standard Odoo only</b> &mdash; depends on Accounting alone; works with any "
            "chart of accounts, with or without the Aktiv modules",
        ])),
        ("How it looks", "SHOTS"),
        ("Active Doc and its plans",
         "<p><b><a href=\"%(adoc)s\" style=\"color:%(accent)s;\">Active Doc</a></b> is a "
         "Ukrainian e-document service by the same author. Receiving, signing and rejecting "
         "documents, and the signed archive, are free and unlimited on every plan. The free "
         "plan sends <b>up to 20 documents a month</b>; larger plans are listed on the "
         "service's site. The module tells you when a limit is reached and never pays for "
         "anything on its own.</p>"
         "<p><b>Which keys work:</b> file keys of Ukrainian qualified trust service providers "
         "&mdash; <code>Key-6.dat</code>, <code>*.jks</code>, <code>*.pfx</code> &mdash; right "
         "in the signing window. With a hardware token, a cloud key or Diia.Signature, sign the "
         "document on the czo.gov.ua site and upload the signature file into the same "
         "window.</p>"),
        ("Getting started",
         "<p>Create an organisation cabinet on Active Doc (one signature with your key), "
         "create an API key there under <i>Organisation &rarr; API keys</i> together with "
         "the address of your Odoo, and paste the key into <i>Settings &rarr; Invoicing "
         "&rarr; Active Doc</i>. <i>Check connection</i> shows the organisation, the plan "
         "and whether the signing window will open from your Odoo address.</p>"),
        ("What's new", "NEWS"),
        ("Also by this author", "FAMILY"),
        ("Support",
         "<p>Questions, bugs, feature requests: <b><a href=\"mailto:%(support)s\" "
         "style=\"color:#2563eb;\">%(support)s</a></b>. Answered in English or Ukrainian.</p>"),
    ],
    "family_intro": "A family of modules for companies moving off 1C / BAS onto Odoo. "
                    "The developer's site: <b><a href=\"%(site)s\" "
                    "style=\"color:%(accent)s;\">3a-studio.aktiv.in.ua</a></b>; "
                    "<a href=\"%(catalog)s\" style=\"color:%(accent)s;\">all apps in the "
                    "store</a>.",
    "family": FAMILY_EN,
    "shots": [("screenshot_send.png", "Send for signature: printed form, recipient, PDF preview"),
              ("screenshot_sign.png", "The Active Doc signing window, right inside Odoo"),
              ("screenshot_incoming.png", "Incoming documents appear by themselves"),
              ("screenshot_document.png", "Signed by both sides: signatures and the archive"),
              ("screenshot_list.png", "The Active Doc column in the invoice list, next to Status")],
}

UK = {
    "anchor": "descr-uk",
    "title": "Рахунки підписуються КЕП і йдуть контрагенту — не виходячи з Odoo",
    "subtitle": "Кваліфікований електронний підпис і обмін документами з контрагентами "
                "через сервіс Active Doc",
    "meta": "LGPL-3 &middot; безкоштовно &middot; Odoo %(odoo)s",
    "blocks": [
        ("", "WARNING"),
        ("Якщо ви прийшли з 1С / BAS",
         "<p>У 1С і BAS рахунок робиться в одній програмі, а підписується в іншій — "
         "M.E.Doc чи окремому сервісі ЕДО, — і підписаний примірник потім шукають і "
         "підшивають руками. Тут кнопка — на самому рахунку, вікно підпису відкривається "
         "в Odoo, а підписаний архів повертається до того ж рахунку.</p>"),
        (("Що він робить", [
            "<b>Надіслати на підпис</b> — на проведеному рахунку, акті чи накладній: "
            "друкована форма, отримувач із картки контрагента, перегляд PDF",
            "<b>Підпис в Odoo</b> — вікно підпису Active Doc відкривається тут же, у "
            "діалозі; входити в окремий кабінет не треба",
            "<b>Надіслати</b> — у кабінет контрагента в Active Doc за ЄДРПОУ / РНОКПП або "
            "посиланням у листі; він підписує без реєстрації",
            "<b>Вхідні</b> — документи, надіслані на ваш код, з'являються самі; підписати "
            "або відхилити з причиною, яку побачить відправник",
            "<b>Підписаний архів</b> — щойно підписали обидві сторони, документ, кожен "
            "підпис і протокол перевірки прикріплюються до рахунку",
        ]), ("Як він збудований", [
            "<b>Ваш ключ до Odoo не потрапляє</b> — файл ключа й пароль лишаються у вікні "
            "підпису; Odoo дізнається лише, що документ підписано",
            "<b>Ключ API — лише на сервері</b> — ні в браузері, ні в журналах; вміст "
            "документів теж не журналюється",
            "<b>«Підписано» не на слово</b> — повідомлення вікна перевіряється за адресою "
            "відправника, а стан перепитується в Active Doc",
            "<b>Усі проблеми одразу</b> — перед надсиланням майстер показує все, що "
            "завадить, і що з кожним робити",
            "<b>Лише штатний Odoo</b> — залежить тільки від Бухгалтерії; працює з будь-яким "
            "планом рахунків, з модулями «Актив» або без них",
        ])),
        ("Як це виглядає", "SHOTS"),
        ("Active Doc і тарифи",
         "<p><b><a href=\"%(adoc)s\" style=\"color:%(accent)s;\">Active Doc</a></b> — "
         "український сервіс електронного документообігу того самого автора. Отримання, "
         "підпис і відхилення документів, а також підписаний архів — безкоштовно й без меж "
         "на будь-якому тарифі. Безкоштовний тариф надсилає <b>до 20 документів на "
         "місяць</b>; більші тарифи — на сайті сервісу. Модуль каже, коли межу вичерпано, і "
         "ніколи нічого не оплачує сам.</p>"
         "<p><b>Які ключі підходять:</b> файлові ключі українських ЦСК — "
         "<code>Key-6.dat</code>, <code>*.jks</code>, <code>*.pfx</code> — прямо у вікні "
         "підпису. З апаратним токеном, хмарним ключем чи Дія.Підписом документ підписують на "
         "сайті czo.gov.ua, а файл підпису завантажують у те саме вікно.</p>"),
        ("Як почати",
         "<p>Створіть кабінет організації в Active Doc (один підпис вашим ключем), там же "
         "створіть ключ API в <i>Організація &rarr; Ключі API</i> разом з адресою вашого "
         "Odoo і вставте його в <i>Налаштування &rarr; Виставлення рахунків &rarr; Active "
         "Doc</i>. <i>Перевірити з'єднання</i> покаже організацію, тариф і чи відкриється "
         "вікно підпису з адреси вашого Odoo.</p>"),
        ("Що нового", "NEWS"),
        ("Інші додатки автора", "FAMILY"),
        ("Підтримка",
         "<p>Питання, помилки, побажання: <b><a href=\"mailto:%(support)s\" "
         "style=\"color:#2563eb;\">%(support)s</a></b>. Відповідаємо українською або "
         "англійською.</p>"),
    ],
    "family_intro": "Лінійка для тих, хто переходить з 1С / BAS на Odoo. "
                    "Сайт розробника: <b><a href=\"%(site)s\" "
                    "style=\"color:%(accent)s;\">3a-studio.aktiv.in.ua</a></b>; "
                    "<a href=\"%(catalog)s\" style=\"color:%(accent)s;\">усі додатки в "
                    "магазині</a>.",
    "family": FAMILY_UK,
    "shots": [("screenshot_send.png", "Надіслати на підпис: друкована форма, отримувач, перегляд PDF"),
              ("screenshot_sign.png", "Вікно підпису Active Doc — прямо в Odoo"),
              ("screenshot_incoming.png", "Вхідні документи з'являються самі"),
              ("screenshot_document.png", "Підписано обома сторонами: підписи й архів"),
              ("screenshot_list.png", "Колонка «Active Doc» у списку рахунків — поруч зі «Стан»")],
}


def manifest():
    text = io.open(os.path.join(ROOT, MODULE, "__manifest__.py"), encoding="utf-8").read()
    return ast.literal_eval(text[text.index("{"):])


def ascii_only(text):
    return "".join(c if ord(c) < 128 else "&#%d;" % ord(c) for c in text)


def shots(items):
    rows = []
    for start in range(0, len(items), 2):
        cells = "".join(
            '        <div class="oe_span6"><img src="%s" style="max-width:100%%;'
            'border-radius:8px;" alt="%s"/><p style="color:#888;font-size:12px;">%s</p></div>\n'
            % (name, alt, alt) for name, alt in items[start:start + 2])
        rows.append('      <div class="oe_row">\n%s      </div>\n' % cells)
    return "".join(rows)


def news(lang, series):
    out = []
    for index, (version, month, year, en, uk) in enumerate(NEWS):
        border = "2px solid #ffd25a" if index == 0 else "1px solid #cfd9e8"
        names = MONTHS if lang == "en" else MONTHS_UK
        when = "%s %d" % (names[MONTHS.index(month)], year)
        label = " &ndash; ".join("%s.%s" % (series, part.strip()) for part in version.split("–"))
        out.append('      <div style="border:%s;border-radius:8px;padding:12px 16px;'
                   'margin-bottom:10px;">\n        <b>%s</b> &mdash; %s<br/>\n        %s\n'
                   '      </div>\n' % (border, label, when, en if lang == "en" else uk))
    return "".join(out)


def family(spec, values):
    items = "".join("        <li><b>%s</b> &mdash; %s</li>\n" % pair for pair in spec["family"])
    return "      <p>%s</p>\n      <ul>\n%s      </ul>\n" % (spec["family_intro"] % values, items)


def half(spec, lang, values):
    panel = "" if lang == "en" else ' style="background:#f5f3fb;border-radius:10px;padding:16px;"'
    out = ['  <div id="%s"><br/><br/><br/><br/><br/></div>\n' % spec["anchor"],
           '  <div class="oe_row oe_spaced"%s>\n' % panel,
           '    <h2 class="oe_slogan" style="color:%s;">%s</h2>\n' % (ACCENT, spec["title"]),
           '    <h3 class="oe_slogan">%s</h3>\n' % spec["subtitle"],
           '    <p class="oe_mt32" style="text-align:center;color:#888;">%s</p>\n'
           % (spec["meta"] % values),
           '  </div>\n\n']
    for block in spec["blocks"]:
        out.append('  <div class="oe_row oe_spaced">\n')
        if isinstance(block[0], tuple):
            for heading, items in block:
                out.append('    <div class="oe_span6">\n'
                           '      <h3 class="oe_slogan" style="text-align:left;">%s</h3>\n'
                           '      <ul>\n%s      </ul>\n    </div>\n' % (
                               heading, "".join("        <li>%s</li>\n" % i for i in items)))
        else:
            heading, body = block
            if body == "SHOTS":
                body = shots(spec["shots"])
            elif body == "NEWS":
                body = news(lang, values["series"])
            elif body == "FAMILY":
                body = family(spec, values)
            elif body == "WARNING":
                title, items = WARN_EN if lang == "en" else WARN_UK
                body = "      %s\n" % (WARNING_BOX % (title, "".join(
                    "          <li>%s</li>\n" % (item % values) for item in items)))
            else:
                body = "      %s\n" % (body % values)
            title_html = ('      <h3 class="oe_slogan" style="text-align:left;">%s</h3>\n' % heading
                          if heading else "")
            out.append('    <div class="oe_span12">\n%s%s    </div>\n' % (title_html, body))
        out.append('  </div>\n\n')
    return "".join(out)


def build():
    data = manifest()
    series = ".".join(data["version"].split(".")[:2])
    values = {"version": data["version"], "series": series, "odoo": series.split(".")[0],
              "support": data["support"], "accent": ACCENT,
              "catalog": CATALOG, "site": SITE, "adoc": ADOC}
    page = [
        '<section class="oe_container">\n',
        '  <p class="oe_mt8" style="text-align:center;">\n',
        '    <a href="#descr-en" style="color:%s;font-weight:bold;">English</a>\n' % ACCENT,
        '    &middot;\n',
        '    <a href="#descr-uk" style="color:%s;font-weight:bold;">Українською</a>\n' % ACCENT,
        '  </p>\n',
        '  <div class="oe_row oe_spaced">\n',
        '    <img src="banner_wide.png" style="max-width:100%;border-radius:10px;"\n',
        '         alt="Active Doc &#8212; sign with KEP and send without leaving Odoo"/>\n',
        '  </div>\n\n',
        half(EN, "en", values),
        half(UK, "uk", values),
        '</section>\n',
    ]
    footer = desc_footer()
    if footer is None:
        raise SystemExit("підвал опису — з 3A tools/store/add_desc_footer.py, а 3A не знайдено "
                         "(TOOLS_3A_STORE=<тека 3A>/tools/store); опис не записано")
    return footer.with_footer(ascii_only("".join(page)))


def desc_footer():
    """Модуль підвалу опису з 3A (`tools/store/add_desc_footer.py`) або None.

    В кінці опису КОЖНОГО додатка — розробник, пошта й уся лінійка (правило власника
    08.10.2026, 3A STORE-CONVENTIONS §2-квінт). Текст підвалу один на всі репо й живе лише в
    3A; шукаємо його поруч із репо, у ~/Projects/adealer, на VPS або за `TOOLS_3A_STORE`.
    """
    for folder in (os.environ.get("TOOLS_3A_STORE"),
                   os.path.join(os.path.dirname(ROOT), "adealer", "tools", "store"),
                   os.path.join(os.path.expanduser("~"), "Projects", "adealer", "tools", "store"),
                   "/home/ubuntu/3A/tools/store"):
        if folder and os.path.isfile(os.path.join(folder, "add_desc_footer.py")):
            if folder not in sys.path:
                sys.path.insert(0, folder)
            import add_desc_footer  # noqa: E402
            return add_desc_footer
    return None


def main():
    out = os.path.join(ROOT, MODULE, "static", "description", "index.html")
    text = build()
    io.open(out, "w", encoding="ascii", newline="\n").write(text)
    print("%s index.html %d bytes" % (MODULE, len(text)))


if __name__ == "__main__":
    main()
