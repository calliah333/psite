from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]

ARTICLES = {
    "portfolio": ("PCB Design Portfolio", "Stuff I've done"),
    "bb60": ("BB60", "A universal 60% PCB"),
    "daal": ("Daal", "A lentil-inspired 60%"),
    "2001": ("2001", "A simple TKL PCB"),
    "liberi": ("Liberi", "A 65XT PCB"),
    "about-me": ("About Me", "I make keyboards and keyboard accessories"),
    "evalice": ("Evalice", "An Evangelion themed Alice"),
    "collection": ("Keyboard Collection", "All (most) of My Keyboards"),
}

REDIRECTS = {
    "form": "https://forms.gle/GxDg6JspqJ7cNVmx8",
    "sauce": "https://github.com/Sleepdealr/sleepsite",
    "rpguide": "https://github.com/Sleepdealr/RP2040-designguide",
    "pcbtips": "https://gist.github.com/Sleepdealr/ab05f5edb82eae9e0393f4d63da55adf",
    "lastfm": "https://last.fm/user/Sleepdealr",
    "letterboxd": "https://letterboxd.com/calliah/",
    "git": "https://github.com/sleepdealr/",
    "a7c": "https://ibb.co/album/HD8cSx",
}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for name in ("href", "src"):
            if name in attrs:
                self.targets.append(attrs[name])


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tempdir = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, tempdir)
        cls.output = tempdir / "public"
        subprocess.run(
            ["zola", "build", "--output-dir", str(cls.output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def page(self, route):
        return (self.output / route.strip("/") / "index.html").read_text()

    def test_all_articles_render(self):
        for slug, (title, marker) in ARTICLES.items():
            html = self.page(f"article/{slug}")
            with self.subTest(slug=slug):
                self.assertIn(title, html)
                self.assertIn(marker, html)
                self.assertIn("Published:", html)
                self.assertIn("Updated:", html)

    def test_index_listing_and_contact_render(self):
        home = (self.output / "index.html").read_text()
        self.assertIn("Hi, I'm Calliah", home)
        self.assertIn("PCB Design Portfolio", home)

        listing = self.page("articles")
        for title, _ in ARTICLES.values():
            self.assertIn(title, listing)

        contact = self.page("contact")
        self.assertIn("@calliah_", contact)
        self.assertIn("sleepdealer01 at protonmail.com", contact)

    def test_all_redirects_render(self):
        for route, target in REDIRECTS.items():
            with self.subTest(route=route):
                self.assertIn(target, self.page(route))

    def test_all_media_are_published(self):
        source = {path.name for path in (ROOT / "static/media").iterdir()}
        published = {path.name for path in (self.output / "media").iterdir()}
        self.assertEqual(42, len(source))
        self.assertEqual(source, published)

    def test_internal_links_resolve(self):
        pages = {}
        for html_path in self.output.rglob("*.html"):
            parser = Links()
            parser.feed(html_path.read_text())
            pages[html_path] = parser

        for html_path, parser in pages.items():
            for target in parser.targets:
                parsed = urlparse(target)
                if parsed.scheme in {"mailto", "data"}:
                    continue
                if parsed.netloc and parsed.netloc != "sleepdealer.xyz":
                    continue
                if not parsed.path and parsed.fragment:
                    candidate = html_path
                else:
                    path = unquote(parsed.path)
                    if path.startswith("/"):
                        candidate = self.output / path.lstrip("/")
                    else:
                        candidate = html_path.parent / path
                    if candidate.is_dir() or not candidate.suffix:
                        candidate /= "index.html"
                with self.subTest(page=html_path.relative_to(self.output), target=target):
                    self.assertTrue(candidate.is_file(), f"missing {candidate}")
                    if parsed.fragment and candidate.suffix == ".html":
                        self.assertIn(parsed.fragment, pages[candidate].ids)

    def test_runtime_configuration_is_valid(self):
        if shutil.which("docker"):
            subprocess.run(
                ["docker", "compose", "config", "-q"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )


if __name__ == "__main__":
    unittest.main()
