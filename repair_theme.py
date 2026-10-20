#!/usr/bin/env python3
"""
repair_theme.py  (GOOD HEALTH HOSPITAL)

Rebuilds the files that the theme installation overwrote, starting again from the version you last
committed in git (HEAD), so nothing newer is lost. Only the styling changes are applied:

  templates/base.html                      new sidebar layout, built from YOUR current menu links and conditions
  templates/accounts/dashboard.html        inline <style> removed, tiles use the new classes
  templates/pharmacy/*.html                links become buttons, inline styles removed
  appointments/.../book.html               one class added to the time picker
  website templates                        the five wrongly named files are put under their real names
  old per-app static folders               removed (everything is in the root static folder now)

Run it from the project folder:   python repair_theme.py
Every file it replaces is first copied to a backup folder (printed at the end).
"""
import os, re, shutil, subprocess, sys, time

ROOT = os.getcwd()
BACKUP = os.path.join(os.environ.get("TEMP", ROOT), "theme_backup_" + time.strftime("%H%M%S"))
done, warned = [], []

def say(kind, msg):
    (warned if kind == "WARN" else done).append(msg)
    print(f"{kind:5} {msg}")

def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    return r.returncode, r.stdout

def head(path):
    code, out = git("show", f"HEAD:{path}")
    return out if code == 0 else None

def tracked(path):
    code, out = git("ls-files", "--", path)
    return code == 0 and out.strip() != ""

def backup(path):
    if os.path.exists(path):
        dst = os.path.join(BACKUP, os.path.relpath(path, ROOT)); os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)

def write(path, text):
    backup(path); os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f: f.write(text)

if not os.path.isdir(os.path.join(ROOT, ".git")) or not os.path.exists(os.path.join(ROOT, "manage.py")):
    sys.exit("Run this from the project folder (the one with manage.py and .git).")

# ------------------------------------------------------------------ 1. base.html
BASE_HEAD = '{% load static %}<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <meta name="theme-color" content="#0a5871">\n  <title>{% block title %}Welcome{% endblock %} | GOOD HEALTH HOSPITAL</title>\n  <link rel="icon" type="image/png" href="{% static \'img/favicon.png\' %}">\n  <script src="{% static \'js/theme-boot.js\' %}"></script>\n  <link rel="stylesheet" href="{% static \'css/theme.css\' %}">\n  {% with app=request.resolver_match.app_name %}{% if app %}<link rel="stylesheet" href="{% static \'css/\'|add:app|add:\'.css\' %}">{% endif %}{% endwith %}\n  {% block extra_css %}{% endblock %}\n</head>\n<body>\n{% static \'img/icons.svg\' as icons %}\n  <div class="bg-orbs" aria-hidden="true"><span></span><span></span><span></span></div>\n  <div class="load-bar" id="loadBar" aria-hidden="true"></div>\n\n  <div class="toasts" aria-live="polite">\n    {% for message in messages %}\n      <div class="toast {{ message.tags }}" role="status"><span class="toast-text">{{ message }}</span><button class="toast-x" type="button" aria-label="Dismiss">&times;</button></div>\n    {% endfor %}\n  </div>\n\n  <div class="shell{% if not user.is_authenticated %} no-sidebar{% endif %}">\n    {% if user.is_authenticated %}\n    <aside class="sidebar" id="sidebar" aria-label="Main menu">\n      <a class="brand" href="{% url \'accounts:dashboard\' %}">\n        <span class="brand-mark"><img src="{% static \'img/logo-mark.png\' %}" alt="" width="50" height="50"></span>\n        <span class="brand-text">GOOD HEALTH<small>HOSPITAL</small></span>\n      </a>\n      <nav class="nav">\n'
BASE_TAIL = '      </nav>\n      <div class="side-foot">\n        <div class="user-chip">\n          <span class="avatar">{{ user.first_name|default:user.username|slice:":1"|upper }}</span>\n          <span class="user-meta"><strong>{{ user.get_full_name|default:user.username }}</strong><small>{{ user.get_role_display }}</small></span>\n        </div>\n        <div class="side-actions">\n          <form class="logout-form" method="post" action="{% url \'accounts:logout\' %}">\n            {% csrf_token %}\n            <button class="logout-btn" type="submit" title="Log out"><svg class="ic" aria-hidden="true"><use href="{{ icons }}#i-logout"/></svg><span>Log out</span></button>\n          </form>\n          <button class="collapse-btn" id="collapseBtn" type="button" title="Collapse menu" aria-label="Collapse menu"><svg class="ic" aria-hidden="true"><use href="{{ icons }}#i-chevrons"/></svg></button>\n        </div>\n      </div>\n    </aside>\n    <div class="scrim" id="scrim"></div>\n    {% endif %}\n\n    <div class="content">\n      <header class="topbar">\n        {% if user.is_authenticated %}<button class="icon-btn" id="navToggle" type="button" aria-label="Open menu"><svg class="ic" aria-hidden="true"><use href="{{ icons }}#i-menu"/></svg></button>{% endif %}\n        <span class="top-brand">GOOD HEALTH HOSPITAL</span>\n      </header>\n      <main id="main">\n        {% block content %}{% endblock %}\n      </main>\n    </div>\n  </div>\n\n  <script src="{% static \'js/theme.js\' %}"></script>\n</body>\n</html>\n'
ICONS = {
 "accounts:dashboard":"grid","patients:my_profile":"user","cases:mine":"folder","cases:new":"alert","laboratory:mine":"flask",
 "pharmacy:mine":"pill","appointments:mine":"calendar","datarequests:mine":"shield","departments:list":"building",
 "patients:staff_register":"userplus","website:manage_posts":"pen","cases:home":"folder","datarequests:manage":"shield",
 "facilities:my_ward":"bed","attendance:mine":"clock","attendance:roster_mine":"calcheck","attendance:roster":"calgrid",
 "attendance:team":"users","laboratory:worklist":"flask","pharmacy:worklist":"pill","appointments:staff_list":"calendar",
 "patients:list":"heart","patients:family_list":"home","facilities:overview":"hospital","facilities:ward_staff":"users",
 "facilities:admission_list":"door","accounts:staff_list":"badge","website:manage_home":"globe","core:audit_list":"list",
}
NAMESPACE_ICON = {"billing":"receipt","appointments":"calendar","pharmacy":"pill","laboratory":"flask","cases":"folder",
                  "patients":"heart","facilities":"hospital","attendance":"clock","website":"globe","datarequests":"shield"}

def fix_base():
    src = head("templates/base.html")
    if src is None: return say("WARN", "templates/base.html is not in git; skipped")
    if "{% block content %}" not in src or "<nav>" not in src: return say("WARN", "base.html has an unexpected shape; skipped")
    # every {% load ... %} line of the committed menu must survive (the notification and appointment tags need them)
    libs = []
    for m in re.finditer(r"\{%\s*load\s+([^%]+?)\s*%\}", src):
        libs += [x for x in m.group(1).split() if x != "static" and x not in libs]
    head_text = BASE_HEAD.replace("{% load static %}", "{% load static " + " ".join(libs) + " %}", 1) if libs else BASE_HEAD
    a = src.index("<nav>") + len("<nav>")
    b = src.index("<form method=\"post\" action=\"{% url 'accounts:logout' %}\">", a)
    nav = src[a:b]
    unknown = []
    def link(m):
        name, label = m.group(1), m.group(2).strip()
        plain = re.sub(r"\s*\(\s*\)", "", re.sub(r"\{%.*?%\}|\{\{.*?\}\}", "", label)).strip()
        icon = ICONS.get(name) or NAMESPACE_ICON.get(name.split(":")[0]) or "list"
        if name not in ICONS: unknown.append(f"{name} -> icon '{icon}'")
        return (f'<a class="nav-link" href="{{% url \'{name}\' %}}" title="{plain}">'
                f'<svg class="ic" aria-hidden="true"><use href="{{{{ icons }}}}#i-{icon}"/></svg><span>{label}</span></a>')
    nav2 = re.sub(r"""<a href="\{% url '([a-z_]+:[a-z_]+)' %\}">([^<]+)</a>""", link, nav)
    left = len(re.findall(r"<a\s", nav2)) - nav2.count('class="nav-link"')
    if left: say("WARN", f"base.html: {left} menu link(s) have a different shape and were left unconverted; send me the file")
    marker = '{% if user.role == "main_admin" or user.role == "sub_admin" %}\n'
    if nav2.count(marker) == 1:
        nav2 = nav2.replace(marker, marker + '      <div class="nav-label">Administration</div>\n')
    else:
        say("WARN", "base.html: could not place the 'Administration' heading (no harm done)")
    nav2 = nav2.replace("</nav>", "").rstrip() + "\n"
    result = head_text + nav2 + BASE_TAIL
    write(os.path.join(ROOT, "templates", "base.html"), result)
    # safety check: nothing the committed menu used may be missing from the rebuilt one
    tags = lambda t: set(re.findall(r"\{%\s*(\w+)", t)) - {"endif", "endfor", "endwith", "endblock", "else", "elif", "comment", "endcomment"}
    urls = lambda t: set(re.findall(r"\{% url '([\w:]+)'", t))
    for lost in sorted(tags(src) - tags(result)): say("WARN", f"base.html: template tag '{lost}' was in your menu but is missing now")
    for lost in sorted(urls(src) - urls(result)): say("WARN", f"base.html: menu link '{lost}' is missing now")
    for lib in libs: say("INFO", f"base.html: kept {{% load {lib} %}}")
    say("OK", f"templates/base.html rebuilt from your committed menu ({len(re.findall('nav-link', nav2))//1} link markers)")
    for u in unknown: say("INFO", f"menu link not in my icon list: {u}")
    others = set(re.findall(r"\{% block (\w+) %\}", src)) - {"title", "content"}
    if others: say("WARN", f"base.html had extra blocks {sorted(others)} which the new layout does not have; tell me")

# ------------------------------------------------------------------ 2. dashboard
def fix_dashboard():
    p = "templates/accounts/dashboard.html"
    s = head(p)
    if s is None: return say("WARN", p + " is not in git; skipped")
    s, n = re.subn(r"<style>.*?</style>\s*", "", s, count=1, flags=re.S)
    s, n1 = re.subn(r'<div class="stat"><a href="(.*?)"><div class="n">(.*?)</div>(.*?)</a></div>',
                    r'<div class="stat"><a href="\1"><span class="stat-number">\2</span><span class="stat-label">\3</span></a></div>', s)
    s, n2 = re.subn(r'<div class="stat"><div class="n">(.*?)</div>(.*?)</div>',
                    r'<div class="stat"><span class="stat-number">\1</span><span class="stat-label">\2</span></div>', s)
    s = s.replace('<div class="stats">', '<div class="stat-grid">')
    write(os.path.join(ROOT, p), s)
    say("OK", f"{p}: inline style removed, {n1 + n2} tiles converted")
    left = len(re.findall(r'class="n"', s)) + len(re.findall(r"<style|\sstyle=", s))
    if left: say("WARN", f"{p}: {left} old-style leftovers (class=\"n\", <style> or style=) remain; send me this file")

# ------------------------------------------------------------------ 3. pharmacy
PHARMACY = {'worklist.html': [('    <span>\n      <a href="{% url \'pharmacy:drugs\' %}">Drugs</a> &nbsp;\n      <a href="{% url \'pharmacy:stock\' %}">Stock</a>\n    </span>', '    <span class="btn-row">\n      <a class="btn btn-ghost" href="{% url \'pharmacy:drugs\' %}">Drugs</a>\n      <a class="btn btn-ghost" href="{% url \'pharmacy:stock\' %}">Stock</a>\n    </span>'), ('  <p>\n    <a href="?status=open">Waiting or partly dispensed</a>\n    {% for value, label in statuses %}| <a href="?status={{ value }}">{{ label }}</a> {% endfor %}\n  </p>', '  <div class="chips">\n    <a class="chip{% if status == \'open\' %} is-active{% endif %}" href="?status=open">Waiting or partly dispensed</a>\n    {% for value, label in statuses %}<a class="chip{% if status == value %} is-active{% endif %}" href="?status={{ value }}">{{ label }}</a>{% endfor %}\n  </div>'), ('<td><a href="{% url \'pharmacy:prescription\' p.pk %}">{{ p.pk }}</a></td>', '<td><a class="btn btn-sm btn-ghost" href="{% url \'pharmacy:prescription\' p.pk %}">{{ p.pk }}</a></td>'), ('  <p>\n    {% if page_obj.has_previous %}<a href="?status={{ status }}&page={{ page_obj.previous_page_number }}">Previous</a>{% endif %}\n    Page {{ page_obj.number }} of {{ paginator.num_pages }}\n    {% if page_obj.has_next %}<a href="?status={{ status }}&page={{ page_obj.next_page_number }}">Next</a>{% endif %}\n  </p>', '  <div class="pager">\n    {% if page_obj.has_previous %}<a class="btn btn-sm btn-ghost" href="?status={{ status }}&page={{ page_obj.previous_page_number }}">Previous</a>{% endif %}\n    <span>Page {{ page_obj.number }} of {{ paginator.num_pages }}</span>\n    {% if page_obj.has_next %}<a class="btn btn-sm btn-ghost" href="?status={{ status }}&page={{ page_obj.next_page_number }}">Next</a>{% endif %}\n  </div>')], 'drug_list.html': [('    <span>\n      <a href="{% url \'pharmacy:worklist\' %}">Prescriptions</a> &nbsp;\n      <a href="{% url \'pharmacy:stock\' %}">Batches</a>\n      {% if can_receive %}&nbsp; <a class="btn" href="{% url \'pharmacy:receive\' %}">Receive stock</a>{% endif %}\n      {% if can_manage %}&nbsp; <a class="btn" href="{% url \'pharmacy:drug_create\' %}">Add drug</a>{% endif %}\n    </span>', '    <span class="btn-row">\n      <a class="btn btn-ghost" href="{% url \'pharmacy:worklist\' %}">Prescriptions</a>\n      <a class="btn btn-ghost" href="{% url \'pharmacy:stock\' %}">Batches</a>\n      {% if can_receive %}<a class="btn" href="{% url \'pharmacy:receive\' %}">Receive stock</a>{% endif %}\n      {% if can_manage %}<a class="btn" href="{% url \'pharmacy:drug_create\' %}">Add drug</a>{% endif %}\n    </span>'), ('<td><a href="{% url \'pharmacy:drug_update\' d.pk %}">Edit</a></td>', '<td><a class="btn btn-sm btn-ghost" href="{% url \'pharmacy:drug_update\' d.pk %}">Edit</a></td>')], 'stock.html': [('    <span>\n      <a href="{% url \'pharmacy:drugs\' %}">Drugs</a> &nbsp;\n      <a href="{% url \'pharmacy:worklist\' %}">Prescriptions</a>\n      {% if can_receive %}&nbsp; <a class="btn" href="{% url \'pharmacy:receive\' %}">Receive stock</a>{% endif %}\n    </span>', '    <span class="btn-row">\n      <a class="btn btn-ghost" href="{% url \'pharmacy:drugs\' %}">Drugs</a>\n      <a class="btn btn-ghost" href="{% url \'pharmacy:worklist\' %}">Prescriptions</a>\n      {% if can_receive %}<a class="btn" href="{% url \'pharmacy:receive\' %}">Receive stock</a>{% endif %}\n    </span>'), ('{% if can_manage %}<a href="{% url \'pharmacy:adjust\' b.pk %}">Write off</a>{% endif %}</li>', '{% if can_manage %}<a class="btn btn-sm danger" href="{% url \'pharmacy:adjust\' b.pk %}">Write off</a>{% endif %}</li>'), ('  <p>{% if show_all %}Showing all batches. <a href="?">Only batches with stock</a>{% else %}Showing batches with stock. <a href="?show=all">Show all</a>{% endif %}</p>', '  <div class="chips">\n    {% if show_all %}<span>Showing all batches.</span> <a class="chip" href="?">Only batches with stock</a>{% else %}<span>Showing batches with stock.</span> <a class="chip" href="?show=all">Show all</a>{% endif %}\n  </div>'), ('<td><a href="{% url \'pharmacy:adjust\' b.pk %}">Adjust</a></td>', '<td><a class="btn btn-sm btn-ghost" href="{% url \'pharmacy:adjust\' b.pk %}">Adjust</a></td>'), ('  <p>\n    {% if page_obj.has_previous %}<a href="?{% if show_all %}show=all&{% endif %}page={{ page_obj.previous_page_number }}">Previous</a>{% endif %}\n    Page {{ page_obj.number }} of {{ paginator.num_pages }}\n    {% if page_obj.has_next %}<a href="?{% if show_all %}show=all&{% endif %}page={{ page_obj.next_page_number }}">Next</a>{% endif %}\n  </p>', '  <div class="pager">\n    {% if page_obj.has_previous %}<a class="btn btn-sm btn-ghost" href="?{% if show_all %}show=all&{% endif %}page={{ page_obj.previous_page_number }}">Previous</a>{% endif %}\n    <span>Page {{ page_obj.number }} of {{ paginator.num_pages }}</span>\n    {% if page_obj.has_next %}<a class="btn btn-sm btn-ghost" href="?{% if show_all %}show=all&{% endif %}page={{ page_obj.next_page_number }}">Next</a>{% endif %}\n  </div>')], 'form.html': [('      <button class="btn" type="submit">{{ submit_label }}</button>\n      <a href="{{ cancel_url }}">Cancel</a>', '      <div class="btn-row">\n        <button class="btn" type="submit">{{ submit_label }}</button>\n        <a class="btn btn-ghost" href="{{ cancel_url }}">Cancel</a>\n      </div>')], 'prescribe.html': [('    <a href="{% url \'cases:detail\' case.pk %}">Back to the case</a>', '    <a class="btn btn-ghost" href="{% url \'cases:detail\' case.pk %}">Back to the case</a>'), ('<div class="card" style="border:2px solid #b00020;">', '<div class="card allergy-warning">'), ('      <button class="btn" type="submit">Send to the pharmacy</button>\n      <a href="{% url \'cases:detail\' case.pk %}">Cancel</a>', '      <div class="btn-row">\n        <button class="btn" type="submit">Send to the pharmacy</button>\n        <a class="btn btn-ghost" href="{% url \'cases:detail\' case.pk %}">Cancel</a>\n      </div>')], 'prescription_detail.html': [('    <a href="{{ back_url }}">Back</a>', '    <a class="btn btn-ghost" href="{{ back_url }}">Back</a>'), ('<div class="card" style="border:2px solid #b00020;">', '<div class="card allergy-warning">')], 'my_prescriptions.html': [('<td><a href="{% url \'pharmacy:prescription\' p.pk %}">View</a></td>', '<td><a class="btn btn-sm btn-ghost" href="{% url \'pharmacy:prescription\' p.pk %}">View</a></td>')], '_case_prescriptions.html': [('<td><a href="{% url \'pharmacy:prescription\' p.pk %}">{{ p.pk }}</a></td>', '<td><a class="btn btn-sm btn-ghost" href="{% url \'pharmacy:prescription\' p.pk %}">{{ p.pk }}</a></td>')]}

def fix_pharmacy():
    for name, pairs in PHARMACY.items():
        cands = [f"templates/pharmacy/{name}", f"pharmacy/templates/pharmacy/{name}"]
        path = next((c for c in cands if tracked(c)), None)
        if path is None: say("WARN", f"pharmacy/{name}: not in git at the usual places; skipped"); continue
        s = head(path); applied = 0
        for old, new in pairs:
            if old in s: s = s.replace(old, new); applied += 1
        write(os.path.join(ROOT, path), s)
        miss = len(pairs) - applied
        say("OK" if not miss else "WARN", f"{path}: {applied}/{len(pairs)} changes applied" + ("" if not miss else " (the rest already differ in your version)"))
        if re.search(r"<style|\sstyle=", s): say("WARN", f"{path} still has an inline style; send me this file")
    stray = "templates/pharmacy/_case_prescriptions.html"
    if os.path.exists(os.path.join(ROOT, stray)) and not tracked(stray) and tracked("pharmacy/templates/pharmacy/_case_prescriptions.html"):
        backup(os.path.join(ROOT, stray)); os.remove(os.path.join(ROOT, stray))
        say("OK", f"removed {stray} (it hid the real partial inside the pharmacy app)")

# ------------------------------------------------------------------ 4. appointments book.html
def fix_book():
    p = "appointments/templates/appointments/book.html"
    s = head(p)
    if s is None: return say("WARN", p + " is not in git; skipped")
    if s.count("<fieldset>") == 1:
        write(os.path.join(ROOT, p), s.replace("<fieldset>", '<fieldset class="slot-picker">')); say("OK", p + ": time-picker class added")
    elif 'slot-picker' in s: say("OK", p + ": already has the class")
    else: say("WARN", p + ": no plain <fieldset> found; the time picker keeps the default look")

# ------------------------------------------------------------------ 5. website names, stray files
RENAMES = [("website/templates/website/blog.html", "website/templates/website/blog_list.html"),
           ("website/templates/website/manage/doctors.html", "website/templates/website/manage/doctor_list.html"),
           ("website/templates/website/manage/messages.html", "website/templates/website/manage/message_list.html"),
           ("website/templates/website/manage/posts.html", "website/templates/website/manage/post_list.html"),
           ("website/templates/website/manage/services.html", "website/templates/website/manage/service_list.html")]
def fix_website():
    for stray, real in RENAMES:
        sp, rp = os.path.join(ROOT, stray), os.path.join(ROOT, real)
        if os.path.exists(sp) and not tracked(stray):
            if os.path.exists(rp):
                write(rp, open(sp, encoding="utf-8").read()); os.remove(sp); say("OK", f"{stray} -> {real}")
            else: say("WARN", f"{real} does not exist; left {stray} alone")

OLD_STATIC = ["accounts/static", "appointments/static", "attendance/static", "cases/static", "core/static", "datarequests/static",
              "departments/static", "facilities/static", "laboratory/static", "patients/static", "pharmacy/static", "website/static/website/css"]
def remove_old_static():
    for d in OLD_STATIC:
        full = os.path.join(ROOT, d)
        if os.path.isdir(full) and not tracked(d):
            backup_dir = os.path.join(BACKUP, d); os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
            shutil.move(full, backup_dir); say("OK", f"removed old {d}")

# ------------------------------------------------------------------ 6. icons
RECEIPT = '  <symbol id="i-receipt" viewBox="0 0 24 24"><path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z"/><path d="M9 8h6M9 12h6"/></symbol>\n'
def fix_icons():
    p = os.path.join(ROOT, "static", "img", "icons.svg")
    if not os.path.exists(p): return say("WARN", "static/img/icons.svg not found; install the theme zip first")
    s = open(p, encoding="utf-8").read()
    if 'id="i-receipt"' not in s: write(p, s.replace("</svg>", RECEIPT + "</svg>")); say("OK", "icons.svg: added the receipt icon (billing)")

def find_hospital_name():
    print("\nWhere HOSPITAL_NAME is defined (change its value to \"GOOD HEALTH HOSPITAL\"):")
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("venv", ".venv", ".git", "node_modules", "staticfiles", "static")]
        for f in files:
            if f.endswith(".py") and f != "repair_theme.py":
                path = os.path.join(root, f)
                for n, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
                    if "HOSPITAL_NAME" in line and "{{" not in line:
                        print(f"   {os.path.relpath(path, ROOT)}:{n}: {line.strip()}")

for step in (fix_base, fix_dashboard, fix_pharmacy, fix_book, fix_website, remove_old_static, fix_icons):
    try: step()
    except Exception as e: say("WARN", f"{step.__name__} failed: {e}")
find_hospital_name()
print(f"\nBackups of every replaced file: {BACKUP}")
print(f"{len(done)} steps done, {len(warned)} warnings." + ("  Send me the WARN lines." if warned else "  Now run: python manage.py test"))
