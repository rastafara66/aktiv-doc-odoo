/** @odoo-module **/
/**
 * Вікно Active Doc усередині Odoo — підпис КЕП документа або подання звіту до ДПС.
 *
 * Сторінка — з doc.aktiv.in.ua у <iframe>: ключ і пароль бачить лише вона, Odoo — ні.
 * Після дії сторінка шле батьківському вікну `postMessage({type, id})`: «adoc:signed»
 * (документ підписано), «adoc:reported» (звіт надіслано до ДПС), «adoc:report_updated»
 * (прийшли квитанції). Ми перевіряємо, ЗВІДКИ прийшло повідомлення (origin сервісу),
 * якого воно виду і про ЯКИЙ запис, а сам стан однаково перепитуємо зі свого сервера —
 * повідомленню з браузера на слово не віримо. Сервер може відповісти дією — тоді її й
 * виконуємо (наступний пакет звіту), інакше перечитуємо сторінку.
 */
import { Component, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { componentProps, declareProps, useReactive } from "./owl_compat";

/** Чи це справжнє повідомлення Active Doc потрібного виду саме про цей запис. */
export function isAdocMessage(event, origin, adocId, types) {
    if (!event || !origin || event.origin !== origin) {
        return false;
    }
    const data = event.data;
    return Boolean(data) && typeof data === "object" && (types || []).includes(data.type)
        && Number(data.id) === Number(adocId);
}

/** Чи це справжнє «підписано» від Active Doc саме про цей документ. */
export function isSignedMessage(event, origin, adocId) {
    return isAdocMessage(event, origin, adocId, ["adoc:signed"]);
}

/** Перепитати сервер; відповів дією — виконати її, інакше перечитати сторінку. */
async function refreshAndContinue(env, params) {
    const model = params.refresh_model || "aktiv.doc.document";
    const method = params.refresh_method || "action_refresh";
    let next = null;
    try {
        next = await env.services.orm.call(model, method, [[params.doc_id]]);
    } finally {
        await env.services.action.doAction(next && typeof next === "object" && next.type
            ? next : { type: "ir.actions.client", tag: "soft_reload" });
    }
}

export class AktivDocSignDialog extends Component {
    static template = "aktiv_doc.SignDialog";
    static components = { Dialog };
    props = componentProps(this);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useReactive({ busy: false });
        // Ключ дозволяє вбудовувати вікно лише з однієї адреси бази (CSP
        // frame-ancestors). Відкрито звідкись інакше — браузер покаже порожнечу,
        // тож кажемо людині, у чому справа, замість порожнього вікна.
        this.blocked = Boolean(this.props.allowedOrigin)
            && this.props.allowedOrigin !== window.location.origin;
        this.onMessage = async (event) => {
            if (this.props.shared.done
                    || !isAdocMessage(event, this.props.origin, this.props.adocId,
                                      this.props.messageTypes || ["adoc:signed"])) {
                return;
            }
            this.props.shared.done = true;
            this.state.busy = true;
            let next = null;
            try {
                next = await this.orm.call(this.props.refreshModel || "aktiv.doc.document",
                                           this.props.refreshMethod || "action_refresh",
                                           [[this.props.docId]]);
            } finally {
                this.props.close();
                await this.action.doAction(next && typeof next === "object" && next.type
                    ? next : { type: "ir.actions.client", tag: "soft_reload" });
            }
        };
        onMounted(() => window.addEventListener("message", this.onMessage));
        onWillUnmount(() => window.removeEventListener("message", this.onMessage));
    }

    get here() {
        return window.location.origin;
    }
}
declareProps(AktivDocSignDialog, {
    url: String,
    origin: String,
    allowedOrigin: { type: String, optional: true },
    adocId: Number,
    docId: Number,
    title: { type: String, optional: true },
    messageTypes: { type: Array, optional: true },
    refreshModel: { type: String, optional: true },
    refreshMethod: { type: String, optional: true },
    busyText: { type: String, optional: true },
    shared: Object,
    close: Function,
});

/** Клієнтська дія `aktiv_doc_sign`: (картка документа під низом) + вікно Active Doc. */
async function aktivDocSign(env, action) {
    const params = action.params || {};
    if (params.doc_action) {
        await env.services.action.doAction(params.doc_action);
    } else if (params.reload) {
        // Наступний пакет звіту: спершу показати, що попередній надіслано.
        await env.services.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
    }
    const shared = { done: false };
    env.services.dialog.add(AktivDocSignDialog, {
        url: params.url,
        origin: params.origin,
        allowedOrigin: params.allowed_origin || "",
        adocId: params.adoc_id,
        docId: params.doc_id,
        title: params.title,
        messageTypes: params.message_types || ["adoc:signed"],
        refreshModel: params.refresh_model || "aktiv.doc.document",
        refreshMethod: params.refresh_method || "action_refresh",
        busyText: params.busy_text || "",
        shared,
    }, {
        // Закрили хрестиком: могли й підписати чи надіслати, а повідомлення не дійшло, —
        // перепитуємо стан, щоб картка не брехала.
        onClose: async () => {
            if (shared.done) {
                return;
            }
            await refreshAndContinue(env, params);
        },
    });
}

registry.category("actions").add("aktiv_doc_sign", aktivDocSign);
