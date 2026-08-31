"""СПОВІЩЕННЯ: помилки доходять, але не заливають канал.

Набір поведінковий, а не структурний. Згортання повторів і межа частоти —
саме та логіка, помилка в якій непомітна до найгіршого моменту: канал або
мовчить, коли все горить, або перетворюється на стрічку, у якій нічого не
видно, і сповіщення починають ігнорувати.
"""
import logging
import os
import sys
import tempfile

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_alerts_"))

from qa_common import Report                              # noqa: E402

r = Report("СПОВІЩЕННЯ")

from shop.alerts import (                                 # noqa: E402
    DEDUP_WINDOW, RATE_LIMIT, TelegramErrorHandler,
)


def record(message="Все зламалось", level=logging.ERROR, line=10, **extra):
    rec = logging.LogRecord(
        name="test", level=level, pathname="/app/x.py", lineno=line,
        msg=message, args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


class Spy(TelegramErrorHandler):
    """Той самий обробник, але замість мережі — список надісланого."""

    def __init__(self):
        super().__init__("api")
        self.sent = []

    def emit(self, rec):
        # Повторюємо шлях батька, але без циклу подій: нас цікавлять
        # рішення «слати чи ні», а не сама доставка. Перевірку рекурсії
        # відтворюємо теж — інакше тест перевіряв би не той код.
        import time

        if self._sending:
            return
        now = time.monotonic()
        fingerprint = self._fingerprint(rec)
        if self._is_repeat(fingerprint, now):
            return
        if self._rate_exceeded(now):
            return
        self.sent.append(self._compose(rec))


# ------------------------------------------------------------------ рівень

print("\n--- беремо лише помилки ---")
handler = TelegramErrorHandler("api")
r.check(handler.level == logging.ERROR, "поріг — ERROR", handler.level)
for level, expected in [(logging.DEBUG, False), (logging.INFO, False),
                        (logging.WARNING, False), (logging.ERROR, True),
                        (logging.CRITICAL, True)]:
    passes = level >= handler.level
    r.check(passes == expected, f"{logging.getLevelName(level)} → "
                                f"{'шлемо' if expected else 'мовчимо'}")


# ------------------------------------------------------------- дедуплікація

print("\n--- однакові помилки згортаються ---")
spy = Spy()
for _ in range(5):
    spy.emit(record(line=10))
r.check(len(spy.sent) == 1, "пʼять однакових — одне повідомлення", len(spy.sent))

# Різні місця в коді — різні помилки, кожна варта уваги
spy.emit(record(line=20))
r.check(len(spy.sent) == 2, "інший рядок коду — нове повідомлення", len(spy.sent))

print("\n--- текст не впливає на відбиток ---")
# Інакше «замовлення 41 не знайдено» і «замовлення 42 не знайдено» були б
# різними помилками, і один збій дав би сотні сповіщень.
spy2 = Spy()
spy2.emit(record("Замовлення 41 не знайдено", line=30))
spy2.emit(record("Замовлення 42 не знайдено", line=30))
r.check(len(spy2.sent) == 1, "різні номери в тексті — одна помилка", len(spy2.sent))

print("\n--- вікно згортання скінченне ---")
spy3 = Spy()
spy3.emit(record(line=40))
# Відмотуємо час назад, ніби вікно минуло
key = next(iter(spy3._seen))
spy3._seen[key] -= DEDUP_WINDOW + 1
spy3.emit(record(line=40))
r.check(len(spy3.sent) == 2, "після вікна помилка нагадує про себе", len(spy3.sent))
r.check(DEDUP_WINDOW >= 60, f"вікно не символічне: {DEDUP_WINDOW} с")


# ------------------------------------------------------------ межа частоти

print("\n--- межа частоти ---")
spy4 = Spy()
for i in range(RATE_LIMIT + 10):
    spy4.emit(record(line=100 + i))
r.check(len(spy4.sent) == RATE_LIMIT,
        f"не більше {RATE_LIMIT} за хвилину", len(spy4.sent))
r.check(RATE_LIMIT <= 20, f"межа нижча за ліміт Telegram: {RATE_LIMIT}")


# ------------------------------------------------------------ памʼять

print("\n--- словник відбитків не росте безмежно ---")
spy5 = Spy()
for i in range(900):
    spy5._is_repeat(f"fp{i}", 1000.0 + i)
r.check(len(spy5._seen) <= 600, f"обрізається: {len(spy5._seen)}")


# --------------------------------------------------------------- зміст

print("\n--- у повідомленні є те, за чим шукають ---")
spy6 = Spy()
spy6.emit(record("Впало оновлення", line=200, requestId="abc123",
                 path="/api/orders/7", method="PATCH", status=500,
                 actor="root", event="http.request"))
text = spy6.sent[0]
for needle, label in [("abc123", "requestId"), ("/api/orders/7", "шлях"),
                      ("PATCH", "метод"), ("500", "код"), ("root", "хто"),
                      ("Впало оновлення", "саме повідомлення"),
                      ("api", "сервіс")]:
    r.check(needle in text, f"є {label}")

print("\n--- розмітка не ламається чужими символами ---")
spy7 = Spy()
spy7.emit(record("Помилка <script> & \"лапки\"", line=300))
text = spy7.sent[0]
r.check("&lt;script&gt;" in text, "кутові дужки екрановані", text[:120])
r.check("&amp;" in text, "амперсанд екранований")

print("\n--- довжина обмежена ---")
spy8 = Spy()
spy8.emit(record("х" * 9000, line=400))
r.check(len(spy8.sent[0]) <= 3500,
        f"вкладається в межу Telegram: {len(spy8.sent[0])}")


# ------------------------------------------------------- захист від циклу

print("\n--- помилка відправки не породжує нову ---")
guard = Spy()
guard._sending = True
guard.emit(record(line=500))
r.check(not guard.sent, "поки шлемо, власні помилки ігноруємо")
guard._sending = False
guard.emit(record(line=500))
r.check(len(guard.sent) == 1, "після відправки обробник знову працює")


print("\n--- без циклу подій нічого не падає ---")
# Обробник викликається з синхронного коду. Якщо циклу немає, він має
# промовчати, а не завалити той код, який просто щось залогував.
plain = TelegramErrorHandler("bot")
try:
    plain.emit(record(line=600))
    r.check(True, "виклик поза циклом подій не кидає винятків")
except Exception as exc:
    r.check(False, "виклик поза циклом подій не кидає винятків", str(exc)[:100])

r.done()
