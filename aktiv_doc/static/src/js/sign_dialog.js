/** @odoo-module **/
/**
 * Вікно підпису КЕП Active Doc усередині Odoo.
 *
 * Сторінка підпису — з doc.aktiv.in.ua у <iframe>: ключ і пароль бачить лише
 * вона, Odoo — ні. Після підпису сторінка шле батьківському вікну
 * `postMessage({type: "adoc:signed", id})`. Ми перевіряємо, ЗВІДКИ прийшло
 * повідомлення (origin сервісу) і про ЯКИЙ документ, а сам стан однаково
 * перепитуємо зі свого сервера — повідомленню з браузера на слово не віримо.
 */
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/** Чи це справжнє «підписано» від Active Doc саме про цей документ. */
export function isSignedMessage(event, origin, adocId) {
    if (!event || !origin || event.origin !== origin) {
        return false;
    }
    const data = event.data;
    return Boolean(data) && typeof data === "object" && data.type === "adoc:signed"
        && Number(data.id) === Number(adocId);
}

export class AktivDocSignDialog extends Component {
    static template = "aktiv_doc.SignDialog";
    static components = { Dialog };
    static props = {
        url: String,
        origin: String,
        allowedOrigin: { type: String, optional: true },
        adocId: Number,
        docId: Number,
        title: { type: String, optional: true },
        shared: Object,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ busy: false });
        // Ключ дозволяє вбудовувати вікно лише з однієї адреси бази (CSP
        // frame-ancestors). Відкрито звідкись інакше — браузер покаже порожнечу,
        // тож кажемо людині, у чому справа, замість порожнього вікна.
        this.blocked = Boolean(this.props.allowedOrigin)
            && this.props.allowedOrigin !== window.location.origin;
        this.onMessage = async (event) => {
            if (this.props.shared.done
                    || !isSignedMessage(event, this.props.origin, this.props.adocId)) {
                return;
            }
            this.props.shared.done = true;
            this.state.busy = true;
            try {
                await this.orm.call("aktiv.doc.document", "action_refresh", [[this.props.docId]]);
            } finally {
                this.props.close();
                await this.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
            }
        };
        onMounted(() => window.addEventListener("message", this.onMessage));
        onWillUnmount(() => window.removeEventListener("message", this.onMessage));
    }

    get here() {
        return window.location.origin;
    }
}

/** Клієнтська дія `aktiv_doc_sign`: (картка документа під низом) + вікно підпису. */
async function aktivDocSign(env, action) {
    const params = action.params || {};
    if (params.doc_action) {
        await env.services.action.doAction(params.doc_action);
    }
    const shared = { done: false };
    env.services.dialog.add(AktivDocSignDialog, {
        url: params.url,
        origin: params.origin,
        allowedOrigin: params.allowed_origin || "",
        adocId: params.adoc_id,
        docId: params.doc_id,
        title: params.title,
        shared,
    }, {
        // Закрили хрестиком: могли й підписати, а повідомлення не дійшло, —
        // перепитуємо стан, щоб картка не брехала.
        onClose: async () => {
            if (shared.done) {
                return;
            }
            try {
                await env.services.orm.call("aktiv.doc.document", "action_refresh", [[params.doc_id]]);
            } finally {
                await env.services.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
            }
        },
    });
}

registry.category("actions").add("aktiv_doc_sign", aktivDocSign);
