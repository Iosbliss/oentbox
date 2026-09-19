from unittest import SkipTest

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class PublicBrowserSmokeTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if sync_playwright is None:
            raise SkipTest('Install Playwright and run: playwright install chromium')
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'browser', None):
            cls.browser.close()
        if getattr(cls, 'playwright', None):
            cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def test_home_and_browse_pages_render(self):
        response = self.page.goto(f'{self.live_server_url}/')
        self.assertEqual(response.status, 200)
        self.assertIn('oentbox', self.page.title().lower())
        self.assertTrue(self.page.locator('nav[aria-label="Primary"]').is_visible())

        response = self.page.goto(f'{self.live_server_url}/browse.html?cat=all')
        self.assertEqual(response.status, 200)
        self.assertTrue(self.page.locator('input[name="q"]').is_visible())
        self.assertTrue(self.page.locator('select[name="sort"]').is_visible())
