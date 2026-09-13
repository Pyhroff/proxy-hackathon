class ActionExecutor:

    def __init__(self, browser, perception):
        self.browser = browser
        self.perception = perception

    def execute(self, action):

        try:

            action_type = action["action"]

            if action_type == "fill":
                self.fill(
                    action["element_id"],
                    action["value"]
                )

            elif action_type == "click":
                self.click(
                    action["element_id"]
                )

            elif action_type == "done":
                return {
                    "success": True,
                    "message": "Agent reported task completion."
                }

            elif action_type == "needs_user":
                return {
                    "success": True,
                    "requires_user": True,
                    "message": "User interaction required."
                }

            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action_type}"
                }

            return {
                "success": True,
                "message": f"{action_type} executed successfully."
            }

        except Exception as e:

            print(f"\nACTION FAILED: {e}")

            return {
                "success": False,
                "error": str(e)
            }

    def get_element(self, element_id):

        if element_id not in self.perception.element_map:
            raise ValueError(
                f"Unknown element: {element_id}"
            )

        return self.perception.element_map[element_id]

    def fill(self, element_id, value):

        element = self.get_element(element_id)

        print(
            f"Filling {element_id} with '{value}'"
        )

        element.fill(value)

    def click(self, element_id):

        element = self.get_element(element_id)

        print(
            f"Clicking {element_id}"
        )

        element.click()