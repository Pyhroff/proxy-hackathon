from browser.playwright_controller import PlaywrightController
from perception.page_perception import PagePerception
from agent.agent import Agent
from agent.actions import ActionExecutor
from pathlib import Path


browser = PlaywrightController()


test_page = Path(__file__).parent / "test.html"

browser.navigate(test_page.as_uri())

perception = PagePerception(browser)

executor = ActionExecutor(
    browser,
    perception
)

agent = Agent(
    perception,
    executor,
    "Fill out the application"
)

agent.run()

input("\nPress Enter to close...")

browser.close()