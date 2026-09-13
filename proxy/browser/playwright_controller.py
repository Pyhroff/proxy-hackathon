from playwright.sync_api import sync_playwright
import base64


class PlaywrightController:

    def __init__(self):

        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.launch(
            headless=False
        )

        self.context = self.browser.new_context()

        self.page = self.context.new_page()

        self.cdp = None
        self.cdp_streaming = False
        self.frame_callback = None


    def navigate(self, url):

        self.page.goto(url)


    def get_url(self):

        return self.page.url


    def get_title(self):

        return self.page.title()


    def get_text(self):

        return self.page.locator("body").inner_text()


    def inspect_page(self):

        return {
            "url": self.page.url,
            "title": self.page.title(),
            "text": self.page.locator("body").inner_text()
        }


    def get_interactive_elements(self):

        elements = self.page.locator(
            "button, input, textarea, select, a"
        ).all()

        result = []

        for element in elements:

            tag = element.evaluate(
                "(el) => el.tagName"
            )

            result.append({
                "tag": tag,
                "text": (
                    element.inner_text()
                    if tag not in ["INPUT", "SELECT"]
                    else ""
                ),
                "type": element.get_attribute("type"),
                "name": element.get_attribute("name"),
                "placeholder": element.get_attribute("placeholder"),
                "aria_label": element.get_attribute("aria-label")
            })

        return result


    def click(self, selector):

        self.page.locator(selector).click()


    def fill(self, selector, text):

        self.page.locator(selector).fill(text)


    def screenshot(self, path):

        self.page.screenshot(
            path=path
        )


    def screenshot_base64(self):

        image_bytes = self.page.screenshot(
            type="jpeg",
            quality=70
        )

        return base64.b64encode(
            image_bytes
        ).decode("utf-8")


    def start_cdp_stream(self, callback):

        if self.cdp_streaming:

            return

        self.frame_callback = callback

        self.cdp = self.context.new_cdp_session(
            self.page
        )

        print("CDP session created")


        def handle_frame(params):

            if not self.cdp_streaming:

                return

            frame_data = params.get("data")

            session_id = params.get("sessionId")


            if frame_data:

                print("CDP frame received")


                if self.frame_callback:

                    try:

                        self.frame_callback(
                            frame_data
                        )

                    except Exception as e:

                        print(
                            "CDP frame callback error:",
                            e
                        )


            if session_id:

                try:

                    self.cdp.send(
                        "Page.screencastFrameAck",
                        {
                            "sessionId": session_id
                        }
                    )

                except Exception as e:

                    print(
                        "CDP frame ACK error:",
                        e
                    )


        self.cdp.on(
            "Page.screencastFrame",
            handle_frame
        )


        self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 60,
                "maxWidth": 1000,
                "maxHeight": 800,
                "everyNthFrame": 1
            }
        )


        self.cdp_streaming = True

        print("CDP screencast started")


    def stop_cdp_stream(self):

        if not self.cdp_streaming:

            return

        self.cdp_streaming = False


        if self.cdp:

            try:

                self.cdp.send(
                    "Page.stopScreencast"
                )

            except Exception as e:

                print(
                    "CDP stop error:",
                    e
                )


        self.frame_callback = None

        self.cdp = None

        print("CDP screencast stopped")


    def close(self):

        self.stop_cdp_stream()


        try:

            self.browser.close()

        except Exception:
            pass


        try:

            self.playwright.stop()

        except Exception:
            pass