import secrets

from django.core.cache import cache

CAPTCHA_SESSION_KEY = "register_captcha_answer"


def client_ip(request):
    # REMOTE_ADDR is used on purpose. X-Forwarded-For can be faked by the client,
    # so only trust it if you deploy behind a proxy you control and configure it.
    return request.META.get("REMOTE_ADDR", "unknown")


def hit_rate_limit(request, scope, limit, window):
    """
    Count one attempt for this IP address and return True once the
    number of attempts inside `window` seconds goes above `limit`.
    """
    key = f"ratelimit:{scope}:{client_ip(request)}"
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:  # the key expired between add() and incr()
        cache.set(key, 1, timeout=window)
        count = 1
    return count > limit


def new_captcha(request):
    """Create a small maths question, keep the answer in the session, return the question."""
    operator = secrets.choice(["+", "-", "x"])
    if operator == "-":
        a = secrets.randbelow(8) + 2  # 2 to 9
        b = secrets.randbelow(a - 1) + 1  # 1 to a-1, so the answer is never 0
    else:
        a = secrets.randbelow(9) + 1
        b = secrets.randbelow(9) + 1
    answer = {"+": a + b, "-": a - b, "x": a * b}[operator]
    request.session[CAPTCHA_SESSION_KEY] = answer
    return f"What is {a} {operator} {b}?"
