/** @odoo-module **/
/*
 * Той самий JS Active Doc в Odoo 18, 19 і 20 — питаємо, що вміє OWL, а не номер серії.
 *
 * Odoo 18 і 19 — це OWL 2, Odoo 20 — OWL 3. Для нашого компонента різниця в трьох місцях:
 *
 * - реактивний стан: в OWL 2 — `useState`, в OWL 3 — `proxy` (`useState` прибрано);
 * - props: OWL 2 сам кладе їх у `this.props`, OWL 3 видає лише через `useProps()`;
 * - опис props: OWL 2 хоче `static props` (без нього — попередження в режимі розробника),
 *   а шар сумісності Odoo 20 на `static props` ПАДАЄ.
 *
 * Та сама думка, що й у Python («за наявністю поля»): одна кодова база в трьох гілках,
 * злиття 19.0 → серія без розгалужень. Вирази шаблону — через `this.` (OWL 3 рендерить
 * шаблон із `{this: компонент}`; `this.x` працює й в OWL 2).
 */
import * as owl from "@odoo/owl";

/** Реактивний стан компонента (викликати в `setup`). */
export const useReactive = owl.proxy || owl.useState;

/** Props компонента як поле класу: `props = componentProps(this);` */
export function componentProps(component) {
    return owl.useProps ? owl.useProps() : component.props;
}

/** Опис props — лише для OWL 2: `declareProps(MyComponent, {...})` після класу. */
export function declareProps(ComponentClass, props) {
    if (!owl.useProps) {
        ComponentClass.props = props;
    }
}
