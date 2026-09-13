class PagePerception:

    def __init__(self, browser):
        self.browser = browser
        self.element_map = {}

    def perceive(self):
        page = self.browser.page

        self.element_map = {}

        elements = page.locator(
            "button, input, textarea, select, a"
        ).all()

        result = {
            "url": page.url,
            "title": page.title(),
            "elements": []
        }

        visible_index = 0

        for element in elements:

            if not element.is_visible():
                continue

            tag = element.evaluate(
                "(el) => el.tagName"
            ).lower()

            role = self.get_role(element, tag)
            name = self.get_name(page, element, tag)

            element_id = f"element_{visible_index}"

            self.element_map[element_id] = element

            value = ""

            if tag in ["input", "textarea", "select"]:
                value = element.input_value()
                
            result["elements"].append({
                "id": element_id,
                "role": role,
                "name": name,
                "visible": True,
                "enabled": element.is_enabled()
            })

            visible_index += 1

        return result

    def get_role(self, element, tag):

        explicit_role = element.get_attribute("role")

        if explicit_role:
            return explicit_role

        if tag == "input":

            input_type = element.get_attribute("type")

            if input_type == "checkbox":
                return "checkbox"

            if input_type == "radio":
                return "radio"

            if input_type == "submit":
                return "button"

            return "textbox"

        if tag == "textarea":
            return "textbox"

        if tag == "select":
            return "combobox"

        if tag == "button":
            return "button"

        if tag == "a":
            return "link"

        return tag

    def get_name(self, page, element, tag):

        aria_label = element.get_attribute("aria-label")

        if aria_label:
            return aria_label

        element_html_id = element.get_attribute("id")

        if element_html_id:

            label = page.locator(
                f'label[for="{element_html_id}"]'
            )

            if label.count() > 0:
                return label.inner_text()

        if tag in ["button", "a"]:
            return element.inner_text()

        placeholder = element.get_attribute("placeholder")

        if placeholder:
            return placeholder

        return ""