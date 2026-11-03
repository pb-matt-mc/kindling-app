"""The device matrix every UI phase from 3 on must pass. CSS px; `bars` = browser address and nav bars showing,
`keyboard` = on-screen keyboard open. Installed web apps have no bars, so they use the full height."""
from dataclasses import dataclass, replace

ANDROID_UA = ("Mozilla/5.0 (Linux; Android 16; SM-S931B) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0.0.0 Mobile Safari/537.36")
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/18.0 Mobile/15E148 Safari/604.1")


@dataclass(frozen=True)
class Device:
    name: str
    w: int
    h: int
    dpr: float
    touch: bool
    ua: str = ""
    bars: int = 0        # px the browser UI takes from the height when running in a browser tab
    keyboard: int = 0    # px the keyboard takes when open
    installed: bool = False
    keyboard_open: bool = False

    @property
    def height(self):
        h = self.h
        if not self.installed:
            h -= self.bars
        if self.keyboard_open:
            h -= self.keyboard
        return h

    @property
    def id(self):
        return f"{self.name}{'-installed' if self.installed else ''}{'-kbd' if self.keyboard_open else ''}"

    def variant(self, **kw):
        return replace(self, **kw)


DESKTOPS = [
    Device("laptop-1366x768", 1366, 768, 1, False),
    Device("laptop-1440x900", 1440, 900, 1, False),
    Device("monitor-1920x1080", 1920, 1080, 1, False),
    Device("monitor-2560x1440", 2560, 1440, 1, False),
]
PHONES = [
    Device("s26", 360, 780, 3, True, ANDROID_UA, bars=90, keyboard=330),
    Device("s26-ultra", 412, 891, 3.5, True, ANDROID_UA, bars=95, keyboard=360),
    Device("iphone-se", 375, 667, 2, True, IPHONE_UA, bars=110, keyboard=300),
    Device("iphone-stress", 320, 568, 2, True, IPHONE_UA, bars=100, keyboard=260),
]


def phone_variants(d):
    """browser tab, installed app, and each with the keyboard open."""
    return [d, d.variant(installed=True), d.variant(keyboard_open=True), d.variant(installed=True, keyboard_open=True)]


QUICK = DESKTOPS[:1] + DESKTOPS[-1:] + [PHONES[0], PHONES[0].variant(installed=True), PHONES[1], PHONES[2]]
FULL = DESKTOPS + [v for p in PHONES for v in phone_variants(p)]


# Phones with the on-screen keyboard open (the visible height shrinks), in a browser tab and as an installed app.
KEYBOARD = [v for p in PHONES for v in (p.variant(keyboard_open=True), p.variant(installed=True, keyboard_open=True))]
