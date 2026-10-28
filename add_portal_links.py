"""Adds the portal-links stylesheet to templates/base.html (safe to run twice).
Run from the project folder:  python add_portal_links.py"""
import os, sys

path = os.path.join("templates", "base.html")
if not os.path.exists(path):
    sys.exit("Run this from the project folder (the one with manage.py).")
text = open(path, encoding="utf-8").read()
link = '<link rel="stylesheet" href="{% static \'css/portal-links.css\' %}">'
if "portal-links.css" in text:
    sys.exit("Already added. Nothing to do.")
anchor = '<link rel="stylesheet" href="{% static \'css/theme.css\' %}">'
if text.count(anchor) != 1:
    sys.exit("Could not find the theme.css line in templates/base.html. Send me the first 15 lines of that file.")
# put it after the per-app stylesheet line so these rules win over both
app_line_start = text.find("{% with app=request.resolver_match.app_name %}")
if app_line_start != -1:
    end = text.index("\n", app_line_start)
    text = text[:end + 1] + "  " + link + "\n" + text[end + 1:]
else:
    text = text.replace(anchor, anchor + "\n  " + link, 1)
open(path, "w", encoding="utf-8", newline="\n").write(text)
print("Added. Reload the page with Ctrl+F5.")
