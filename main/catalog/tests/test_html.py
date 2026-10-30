from django.test import SimpleTestCase

from catalog.html import make_short_description, sanitize_html, to_plain_text


class SanitizeHtmlTests(SimpleTestCase):
    def test_keeps_basic_formatting(self):
        html = "<p>One <strong>bold</strong> <em>word</em></p><ul><li>item</li></ul>"
        self.assertEqual(sanitize_html(html), html)

    def test_removes_scripts_styles_and_event_handlers(self):
        dirty = '<p style="color:red" onmouseover="x()">Hi</p><script>alert(1)</script><style>p{}</style>'
        self.assertEqual(sanitize_html(dirty), "<p>Hi</p>")

    def test_links_are_safe(self):
        self.assertEqual(
            sanitize_html('<a href="https://example.com" target="_blank">ok</a>'
                          '<a href="javascript:alert(1)">bad</a>'),
            '<a href="https://example.com" rel="noopener noreferrer nofollow">ok</a>'
            '<a rel="noopener noreferrer nofollow">bad</a>',
        )

    def test_unknown_tags_are_unwrapped(self):
        self.assertEqual(sanitize_html("<div><span>text</span></div>"), "text")

    def test_none_and_empty(self):
        self.assertEqual(sanitize_html(None), "")
        self.assertEqual(sanitize_html("  "), "")

    def test_is_idempotent(self):
        once = sanitize_html('<p>A &amp; B <a href="https://x.test">x</a></p>')
        self.assertEqual(sanitize_html(once), once)


class PlainTextTests(SimpleTestCase):
    def test_strips_tags_and_decodes_entities(self):
        self.assertEqual(to_plain_text("<p>Fish &amp; chips</p><p>that&#8217;s it</p>"),
                         "Fish & chips that’s it")

    def test_short_description_cuts_at_word_limit(self):
        body = "<p>" + " ".join(f"w{i}" for i in range(40)) + "</p>"
        self.assertEqual(make_short_description(body, words=3), "w0 w1 w2…")

    def test_short_description_never_exceeds_the_field_length(self):
        body = "<p>" + " ".join("x" * 100 for _ in range(10)) + "</p>"
        text = make_short_description(body)
        self.assertEqual(len(text), 500)
        self.assertTrue(text.endswith("…"))

    def test_short_description_keeps_short_text_whole(self):
        self.assertEqual(make_short_description("<p>Short.</p>"), "Short.")
