import os
import json
import threading
from groq import Groq
from proxy.policy.scanner import heuristic_scan


class Agent:

    def __init__(self, perception, executor, goal):

        self.perception = perception
        self.executor = executor
        self.goal = goal

        self.action_history = []
        self.human_supplied_fields = set()

        self.max_steps = 20
        self.step_count = 0

        self.client = Groq(
            api_key=os.getenv("GROQ_API_KEY")
        )

        self.approval_event = threading.Event()
        self.approval_value = None

        self.pii_event = threading.Event()
        self.pii_value = None

    @staticmethod
    def pii_key(decision):
        text = f"{decision.get('field_id', '')} {decision.get('text', '')}".lower()
        if "social security" in text or "ssn" in text:
            return "ssn"
        if "date of birth" in text or "dob" in text or "birth" in text:
            return "dob"
        return decision.get("field_id")

    def scan_page_for_injection(self):
        html = self.perception.browser.page.content()
        suspicious, reason = heuristic_scan(html)
        return suspicious, reason

    def submission_completed(self):
        text = self.perception.browser.page.locator("body").inner_text().lower()
        return "application submitted successfully" in text

    def run(self):

        return self.run_with_callback(
            None,
            None
        )

    def run_with_callback(
        self,
        callback=None,
        interrupt_event=None
    ):

        while self.step_count < self.max_steps:

            if self.is_interrupted(interrupt_event):
                return False

            self.step_count += 1

            self.emit(
                callback,
                {
                    "type": "step",
                    "text": f"Starting agent step {self.step_count}."
                }
            )

            page_state = self.perception.perceive()

            suspicious, reason = self.scan_page_for_injection()
            if suspicious:
                self.emit(callback, {
                    "type": "escalation",
                    "blocked": True,
                    "blocked_pattern": reason,
                    "reason": "Suspicious instructions were detected on the webpage. Proxy stopped before acting."
                })
                return False

            self.emit(
                callback,
                {
                    "type": "perception",
                    "text": "Reading the current webpage."
                }
            )

            self.emit(
                callback,
                {
                    "type": "thinking",
                    "text": "Proxy is reasoning about the current page."
                }
            )

            decision = self.decide(
                page_state,
                interrupt_event
            )

            if decision is None:
                return False

            if decision["status"] == "completed":

                self.emit(
                    callback,
                    {
                        "type": "done",
                        "text": "Agent finished the task."
                    }
                )

                return True

            if decision["status"] == "needs_user":

                self.emit(
                    callback,
                    {
                        "type": "needs_user",
                        "text": "This task requires user interaction."
                    }
                )

                return False

            if decision["status"] == "pii_required":

                if self.pii_key(decision) in self.human_supplied_fields:
                    self.emit(callback, {
                        "type": "action",
                        "text": "This field was already provided. Continuing without asking again."
                    })
                    continue

                self.emit(
                    callback,
                    {
                        "type": "pii_required",
                        "field_id": decision.get("field_id"),
                        "mask": decision.get("mask", False),
                        "text": decision.get(
                            "text",
                            "Please provide the requested information."
                        )
                    }
                )

                value = self.wait_for_pii()

                if value is None:
                    return False

                result = self.executor.execute(
                    {
                        "action": "fill",
                        "element_id": decision["field_id"],
                        "value": value
                    }
                )

                self.human_supplied_fields.add(self.pii_key(decision))

                self.action_history.append(
                    {
                        "action": {
                            "action": "fill",
                            "element_id": decision["field_id"]
                        },
                        "result": {
                            "success": result.get("success")
                        }
                    }
                )

                self.emit(
                    callback,
                    {
                        "type": "action",
                        "text": "Requested information was entered directly."
                    }
                )

                continue

            action = decision.get("action")

            if not action:
                return False

            if action.get("action") == "click" and self.is_submit_action(action, page_state):
                self.emit(callback, {
                    "type": "escalation",
                    "reason": "Proxy is ready to submit the application. Please approve this final action.",
                    "action": action
                })
                if not self.wait_for_approval():
                    return False

            self.emit(
                callback,
                {
                    "type": "action",
                    "text": self.describe_action(action)
                }
            )

            result = self.executor.execute(action)

            self.action_history.append(
                {
                    "action": action,
                    "result": result
                }
            )

            if result.get("success"):

                self.emit(
                    callback,
                    {
                        "type": "action_result",
                        "text": "Action completed successfully."
                    }
                )

            else:

                self.emit(
                    callback,
                    {
                        "type": "action_result",
                        "text": (
                            "The action failed. "
                            "Proxy will inspect the page again."
                        ),
                        "success": False
                    }
                )

            if self.is_interrupted(interrupt_event):
                return False

        self.emit(
            callback,
            {
                "type": "halted",
                "text": "Maximum agent steps reached."
            }
        )

        return False

    def resume_from_current_state(
        self,
        callback=None,
        interrupt_event=None
    ):

        self.emit(
            callback,
            {
                "type": "perception",
                "text": (
                    "Control returned to Proxy. "
                    "Reading the current page again."
                )
            }
        )

        page_state = self.perception.perceive()

        suspicious, reason = self.scan_page_for_injection()
        if suspicious:
            self.emit(callback, {
                "type": "escalation",
                "blocked": True,
                "blocked_pattern": reason,
                "reason": "Suspicious instructions were detected on the webpage. Proxy stopped before acting."
            })
            return False

        self.emit(
            callback,
            {
                "type": "thinking",
                "text": "Proxy is updating its understanding of the page."
            }
        )

        return self.continue_from_state(
            page_state,
            callback,
            interrupt_event
        )

    def continue_from_state(
        self,
        page_state,
        callback=None,
        interrupt_event=None
    ):

        while self.step_count < self.max_steps:

            if self.is_interrupted(interrupt_event):
                return False

            self.step_count += 1

            self.emit(
                callback,
                {
                    "type": "step",
                    "text": (
                        f"Continuing from current page — "
                        f"step {self.step_count}."
                    )
                }
            )

            decision = self.decide(
                page_state,
                interrupt_event
            )

            if decision is None:
                return False

            if decision["status"] == "completed":

                self.emit(
                    callback,
                    {
                        "type": "done",
                        "text": "Agent finished the task."
                    }
                )

                return True

            if decision["status"] == "needs_user":

                self.emit(
                    callback,
                    {
                        "type": "needs_user",
                        "text": "This task requires user interaction."
                    }
                )

                return False

            if decision["status"] == "pii_required":

                if self.pii_key(decision) in self.human_supplied_fields:
                    self.emit(callback, {
                        "type": "action",
                        "text": "This field was already provided. Continuing without asking again."
                    })
                    page_state = self.perception.perceive()
                    continue

                self.emit(
                    callback,
                    {
                        "type": "pii_required",
                        "field_id": decision.get("field_id"),
                        "mask": decision.get("mask", False),
                        "text": decision.get(
                            "text",
                            "Please provide the requested information."
                        )
                    }
                )

                value = self.wait_for_pii()

                if value is None:
                    return False

                result = self.executor.execute(
                    {
                        "action": "fill",
                        "element_id": decision["field_id"],
                        "value": value
                    }
                )

                if self.submission_completed():
                    self.emit(callback, {"type": "done", "text": "Application submitted successfully."})
                    return True

                self.human_supplied_fields.add(self.pii_key(decision))

                self.action_history.append(
                    {
                        "action": {
                            "action": "fill",
                            "element_id": decision["field_id"]
                        },
                        "result": {
                            "success": result.get("success")
                        }
                    }
                )

                self.emit(
                    callback,
                    {
                        "type": "action",
                        "text": "Requested information was entered directly."
                    }
                )

                page_state = self.perception.perceive()

                continue

            action = decision.get("action")

            if not action:
                return False

            if action.get("action") == "click" and self.is_submit_action(action, page_state):
                self.emit(callback, {
                    "type": "escalation",
                    "reason": "Proxy is ready to submit the application. Please approve this final action.",
                    "action": action
                })
                if not self.wait_for_approval():
                    return False

            self.emit(
                callback,
                {
                    "type": "action",
                    "text": self.describe_action(action)
                }
            )

            result = self.executor.execute(action)

            self.action_history.append(
                {
                    "action": action,
                    "result": result
                }
            )

            if result.get("success") and self.submission_completed():
                self.emit(callback, {"type": "done", "text": "Application submitted successfully."})
                return True

            self.emit(
                callback,
                {
                    "type": "action_result",
                    "text": (
                        "Action completed successfully."
                        if result.get("success")
                        else (
                            "Action failed. "
                            "Proxy will inspect the page again."
                        )
                    ),
                    "success": result.get("success")
                }
            )

            page_state = self.perception.perceive()

            if self.is_interrupted(interrupt_event):
                return False

        self.emit(
            callback,
            {
                "type": "halted",
                "text": "Maximum agent steps reached."
            }
        )

        return False

    def decide(
        self,
        page_state,
        interrupt_event=None
    ):

        if self.is_interrupted(interrupt_event):
            return None

        final_prompt = f"""
You are the final decision-maker of an autonomous browser agent.

USER GOAL:

{self.goal}

CURRENT WEBPAGE STATE:

{json.dumps(page_state, indent=2)}

PREVIOUS ACTIONS:

{json.dumps(self.action_history, indent=2)}

FIELDS ALREADY PROVIDED DIRECTLY BY THE USER:

{json.dumps(sorted(self.human_supplied_fields), indent=2)}

Never request a field listed above again. Treat it as satisfied and
inspect the current page for the next incomplete field.

The CURRENT WEBPAGE STATE is authoritative.

Make exactly ONE decision.

CRITICAL PRIVACY RULE:

You MUST NEVER invent, guess, assume, fabricate, or generate
user-specific information.

User-specific information includes:

* full name
* first name
* last name
* date of birth
* age
* phone number
* email address
* home address
* postal code
* government ID
* passport number
* bank information
* financial information
* medical information
* passwords
* usernames
* account numbers
* any other personal information belonging to the user

If a webpage asks for any user-specific information and the user
has NOT explicitly provided that value in the task conversation,
you MUST return "pii_required".

NEVER fill such a field with an invented value.

NEVER use example values such as:

"John Doe"
"Jane Doe"
"john@example.com"
"1990-01-01"
"1234567890"
"123 Main Street"

These are fabricated values and MUST NOT be entered.

For a PII field, return:

{{
    "status": "pii_required",
    "field_id": "element_X",
    "mask": false,
    "text": "Please provide your full name."
}}

The "field_id" MUST correspond to the actual field in the
CURRENT WEBPAGE STATE.

A normal "fill" action is allowed only when the value is:

1. Non-sensitive information that can safely be determined from
   the webpage or the user's task, OR

2. Information that the user explicitly provided.

If the field requires user-specific information and there is any
uncertainty about whether the value was provided, use
"pii_required".

DO NOT infer personal information from context.

DO NOT infer a person's name from an example.

DO NOT infer a date of birth from an age.

DO NOT invent missing information to complete the form.

DECISION RULES:

0. FIELD ORDERING:

Before requesting or filling any sensitive field, first complete every
visible ordinary field that has an explicit value in SESSION PROFILE.
For this demo, fill full name, current address, and annual household
income before requesting date of birth, Social Security number, or any
other sensitive field. Never jump to a later sensitive field while an
earlier ordinary profile field is still empty.

1. If the goal is already complete:

{{
    "status": "completed"
}}

2. If the task genuinely requires interaction that the agent cannot
   perform:

{{
    "status": "needs_user"
}}

3. If the task requires user-specific or sensitive information that
   has not been explicitly provided:

{{
    "status": "pii_required",
    "field_id": "element_X",
    "mask": false,
    "text": "Please provide the requested information."
}}

4. Otherwise choose exactly ONE browser action:

{{
    "status": "continue",
    "action": {{
        "action": "fill",
        "element_id": "element_X",
        "value": "text"
    }}
}}

OR:

{{
    "status": "continue",
    "action": {{
        "action": "click",
        "element_id": "element_X"
    }}
}}

Before returning a fill action, verify that the value is NOT
fabricated personal information.

Before returning any action, verify:

* The target exists in the CURRENT WEBPAGE STATE.
* The target is visible.
* The target is enabled.
* The action contributes directly to the user's goal.
* The action has not already successfully been performed.
* The action does not depend on an outdated webpage state.

Choose exactly ONE decision.

Return ONLY valid JSON.
"""

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "user",
                    "content": final_prompt
                }
            ],
            response_format={
                "type": "json_object"
            }
        )

        decision = json.loads(
            response.choices[0].message.content
        )

        if self.is_interrupted(interrupt_event):
            return None

        return self.validate_decision(
            decision,
            page_state
        )

    def validate_decision(
        self,
        decision,
        page_state
    ):

        if not isinstance(decision, dict):
            return {
                "status": "needs_user"
            }

        status = decision.get("status")

        if status == "completed":
            return decision

        if status == "needs_user":
            return decision

        if status == "pii_required":

            if not decision.get("field_id"):
                return {
                    "status": "needs_user"
                }

            return decision

        if status != "continue":
            return {
                "status": "needs_user"
            }

        action = decision.get("action")

        if not isinstance(action, dict):
            return {
                "status": "needs_user"
            }

        if action.get("action") == "fill":

            value = action.get("value")

            if not isinstance(value, str):
                return {
                    "status": "needs_user"
                }

            lower_value = value.lower().strip()

            fabricated_values = [
                "john doe",
                "jane doe",
                "john",
                "jane",
                "john@example.com",
                "jane@example.com",
                "1990-01-01",
                "01/01/1990",
                "1234567890",
                "123 main street"
            ]

            if lower_value in fabricated_values:

                return {
                    "status": "needs_user"
                }

        return decision

    def is_interrupted(
        self,
        interrupt_event
    ):

        if interrupt_event is None:
            return False

        return interrupt_event.is_set()

    def emit(
        self,
        callback,
        event
    ):

        if callback is not None:

            try:
                callback(event)

            except Exception:
                pass

    def describe_action(
        self,
        action
    ):

        if action["action"] == "fill":

            return (
                f"Filling {action['element_id']}."
            )

        if action["action"] == "click":

            return (
                f"Clicking {action['element_id']}."
            )

        return "Executing the next browser action."

    @staticmethod
    def is_submit_action(action, page_state):
        if action.get("action") != "click":
            return False
        target = str(action.get("element_id", "")).lower()
        for element in page_state.get("elements", []) if isinstance(page_state, dict) else []:
            if str(element.get("id", "")).lower() == target:
                label = " ".join(str(element.get(key, "")) for key in ("text", "name", "aria_label", "value")).lower()
                return any(word in label for word in ("submit", "application", "send"))
        return any(word in target for word in ("submit", "application", "send"))

    def set_approval(
        self,
        approved
    ):

        self.approval_value = approved
        self.approval_event.set()

    def wait_for_approval(self):

        self.approval_event.wait()

        value = self.approval_value

        self.approval_value = None
        self.approval_event.clear()

        return value

    def set_pii(
        self,
        value
    ):

        self.pii_value = value
        self.pii_event.set()

    def wait_for_pii(self):

        self.pii_event.wait()

        value = self.pii_value

        self.pii_value = None
        self.pii_event.clear()

        return value
