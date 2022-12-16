from dataclasses import dataclass, field
from enum import Enum
from itertools import chain
from functools import partial
from typing import Any
from selenium import webdriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
import asyncio
import os.path
from os import access, R_OK
from shutil import move
from tempfile import mkdtemp

class SelType(str, Enum):
    CSS = By.CSS_SELECTOR
    LINK_TEXT = By.LINK_TEXT

@dataclass(slots=True)
class PathSelector:
    type: SelType
    path: str

    def __add__(self, other):
        if other.__class__ is not PathSelector: return NotImplemented
        match self.type, other.type:
            case SelType.CSS, SelType.CSS: return PathSelector(SelType.CSS, f'{self.path} {other.path}')
            case _: return Path(self, other)
    def __call__(self, browser, *other):
        return list(map(partial(Element, browser), chain.from_iterable(o.find_elements(self.type.value, self.path) for o in other)))

def yield_selectors(it):
    match it:
        case PathSelector(): yield it
        case str(): yield PathSelector(SelType.CSS, it)
        case list()|tuple():
            for i in it: yield from yield_selectors(it)
        case _: raise ValueError(it)

def to_sel(sel: PathSelector|str):
    if sel.__class__ is PathSelector: return sel
    return PathSelector(SelType.CSS, sel)

class Path(list):
    __slots__ = ()
    def __init__(self, *args):
        list.__init__(self, yield_selectors(it))
    def __add__(self, other):
        if other.__class__ is Path:
            return Path(self[:-1], self[-1] + other[0], other[1:])
        if other.__class__ not in (str, PathSelector): return NotImplemented
        return Path(self[:-1], self[-1] + to_sel(other))
    def __radd__(self, other):
        if other.__class__ not in (str, PathSelector): return NotImplemented
        return Path(to_sel(other) + self[0], self[1:])

    def __call__(self, browser, *other):
        for p in self: other = p(browser, other)
        return other

SelIn = Path|PathSelector|str
def to_path_or_sel(sel: SelIn):
    if sel.__class__ is str: return PathSelector(SelType.CSS, sel)
    return sel

@dataclass(slots=True, frozen=True, unsafe_hash=True)
class Element:
    browser: 'Browser'
    inner: WebElement

    @property
    def text(self) -> str: return self.inner.text
    @property
    def href(self) -> str: return self.browser.get_url(self.inner.get_attribute('href'))
    @property
    def raw_href(self) -> str: return self.inner.get_dom_attribute('href')
    @property
    def dom_href(self) -> str: return self.browser.get_url(self.inner.get_dom_attribute('href'))
    def attr(self, name) -> str: return self.inner.get_attribute(name)

    def scroll_to_middle(self):
        height = self.browser.browser.get_window_size()['height']
        rect = self.inner.rect
        scroll = max(0, rect['y'] - height // 2)
        self.browser.browser.execute_script(f'window.scrollTo(0, {scroll});')

    def click(self):
        self.scroll_to_middle()
        self.inner.click()

    def children(self): return Elements(Element(self.browser, e) for e in self.inner.get_property('children'))

    def parent(self): return Element(self.browser, self.inner.parent)

    def matches(self, sel: SelIn):
        match to_path_or_sel(sel):
            case [PathSelector(SelType.LINK_TEXT, txt)]: return self.inner.text == txt
            case PathSelector(SelType.LINK_TEXT, txt): return self.inner.text == txt
            case sel: return self.inner in sel(self.browser, self.inner.parent)

    def find(self, sel: SelIn): return Elements(to_path_or_sel(sel)(self.browser, self.inner))
    def exists(self, sel: SelIn) -> bool:
        return bool(self.find(sel))
    def one(self): return self
    def maybe_one(self): return self

class Elements(list):
    __slots__ = ()

    def __add__(self, other):
        if other.__class__ is not Elements: return NotImplemented
        return Elements(list.__add__(self, other))

    def children(self): return Elements(chain.from_iterable(map(Element.children, self)))
    def parent(self): return Elements(map(Element.parent, self))
    def find(self, sel: SelIn): return Elements(chain.from_iterable(e.find(sel) for e in self))
    def exists(self, sel: SelIn) -> bool:
        return bool(self.find(sel))
    def filter(self, sel: SelIn): return Elements(filter(lambda x: x.matches(sel), self))

    def one(self):
        if len(self) != 1: raise ValueError(f'Expected single element')
        return self[0]

    def maybe_one(self):
        if len(self) > 1: raise ValueError(f'Expected zero or one elements')
        return self[0] if self else None

__all__ = ('Browser')
@dataclass(slots=True)
class Browser:
    base_url: str
    current_url: str|None = field(init=False, default=None)
    _browser: Any = field(init=False, default=None)
    temp_dir: str|None = field(init=False, default=None)

    @property
    def browser(self):
        if not self._browser:
            self.temp_dir = mkdtemp()
            profile = webdriver.FirefoxProfile()
            profile.set_preference("browser.download.folderList", 2)
            profile.set_preference("browser.download.dir", self.temp_dir)
            profile.set_preference("browser.contentblocking.category", 'strict')
            self._browser = webdriver.Firefox(firefox_profile=profile)
        return self._browser

    def __post_init__(self):
        self.base_url = self.base_url + '/' if not self.base_url.endswith('/') else self.base_url

    async def wait_download(self, name: str, to: str, check_callback):
        path = os.path.join(self.temp_dir, name)
        if os.path.dirname(path) != self.temp_dir: raise ValueError(f'Invalid path {path}')
        while not access(path, R_OK) or not check_callback(path):
            await asyncio.sleep(1)
        await asyncio.sleep(1.5)
        move(path, to)

    @property
    def title(self): return self.browser.title

    def meta(self, name: str):
        el = self.find(f"meta[name='{name}']").maybe_one()
        return el and el.attr('content')

    def get_url(self, path: str):
        if path.startswith('http://') or path.startswith('https://'): return path
        return self.base_url + path.lstrip('/')
    def maybe_get_url(self, path: str|None):
        if not path: return None
        return self.get_url(path)

    def select_frame(self, frame: Element|Elements|None):
        if frame is None:
            self.browser.switch_to.default_content()
        else:
            self.browser.switch_to.frame(frame.one().inner)

    def navigate(self, path: str):
        url = self.get_url(path)
        if self.current_url == url: return
        self.current_url = None
        self.browser.get(url)
        self.current_url = url

    async def maybe_wait(self, sel: SelIn, timeout: int = 5000) -> Elements:
        while not (result := self.find(sel)):
            await asyncio.sleep(0.1)
            timeout -= 100
            if timeout <= 0: return Elements()
        return result

    async def wait(self, sel: SelIn, timeout: int = 5000) -> Elements:
        result = await self.maybe_wait(sel, timeout)
        if not result: raise ValueError(f'Selector {sel} did not appear')
        return result

    def find(self, sel: SelIn) -> Elements:
        return Elements(to_path_or_sel(sel)(self, self.browser))

    def exists(self, sel: SelIn) -> bool:
        return bool(self.find(sel))

    def __enter__(self):
        assert not self._browser
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.current_url = None
        if self._browser:
            self._browser.quit()
            self._browser = None


