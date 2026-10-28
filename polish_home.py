r"""Polishes the one-page home: replaces home.html and installs the v2 styles.
Put this file next to manage.py and run:  python polish_home.py
The previous home.html is kept as home.html.v1. Safe to run again."""
import os, shutil, sys

if not os.path.exists("manage.py"):
    sys.exit("Put this file in the project folder (the one with manage.py) and run it there.")

HOME = os.path.join("website", "templates", "website", "home.html")
CSS_PATH = os.path.join("static", "css", "website.css")
MARK = "/* ===== One-page home v2"

HOME_HTML = r'''{% extends "website/base_public.html" %}
{% block title %}{{ HOSPITAL_NAME|default:"GOOD HEALTH HOSPITAL" }}{% endblock %}
{% block content %}
<section class="hero">
  <div class="hero-logo" aria-hidden="true"></div>
  <p class="hero-kicker">Better Care &middot; Healthier Tomorrow</p>
  <h1>Caring for you and your family</h1>
  <p>Book a visit, register as a patient, and follow your treatment from one secure place.</p>
  <div class="btn-row">
    {% if request.user.is_authenticated %}
      <a class="btn" href="{% url 'accounts:dashboard' %}">Go to my portal</a>
    {% else %}
      <a class="btn" href="{% url 'accounts:login' %}">Login to the portal</a>
      <a class="btn btn-ghost" href="{% url 'patients:register' %}">Register as a patient</a>
    {% endif %}
  </div>
</section>

<div class="quick-bar" aria-label="Key information">
  {% if site.emergency_phone %}<div class="quick-item quick-emergency"><span class="quick-label">Emergency</span><strong>{{ site.emergency_phone }}</strong></div>{% endif %}
  {% if site.phone %}<div class="quick-item"><span class="quick-label">Phone</span><strong>{{ site.phone }}</strong></div>{% endif %}
  {% if site.opening_hours %}<div class="quick-item"><span class="quick-label">Opening hours</span><strong>{{ site.opening_hours|truncatechars:48 }}</strong></div>{% endif %}
  <a class="btn quick-book" href="{% url 'appointments:book' %}">Book an appointment</a>
</div>

<section class="home-section" id="about">
  <div class="section-head"><h2>About us</h2></div>
  <div class="article">
    {% if site.about_text %}{{ site.about_text|linebreaks }}{% else %}<p>Information about the hospital will be added soon.</p>{% endif %}
  </div>
</section>

<section class="home-section is-tint" id="departments">
  <div class="section-head">
    <h2>Departments</h2>
    <p class="section-lead">The teams that look after your health, each led by experienced professionals.</p>
  </div>
  <div class="grid">
    {% for department in departments %}
      <div class="card">
        <span class="card-icon" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg></span>
        <h3>{{ department.name }}</h3><p>{{ department.description }}</p>
      </div>
    {% empty %}
      <p>No departments to show yet.</p>
    {% endfor %}
  </div>
</section>

<section class="home-section" id="doctors">
  <div class="section-head">
    <h2>Our doctors</h2>
    <p class="section-lead">Meet our dedicated team of professionals committed to your health and well-being.</p>
  </div>
  <div class="doc-list">
    {% for d in listings %}
    <article class="doc-profile">
      <div class="doc-photo">
        {% if d.photo %}
          <img src="{{ d.photo.url }}" alt="{{ d.user.get_full_name }}">
        {% else %}
          <div class="doc-photo-empty" role="img" aria-label="No photo yet"></div>
        {% endif %}
      </div>
      <div class="doc-info">
        {% if d.department %}<span class="doc-badge">{{ d.department.name }}</span>{% endif %}
        <h3>Dr. {{ d.user.get_full_name }}</h3>
        {% if d.bio %}<p class="doc-bio">{{ d.bio|linebreaksbr }}</p>{% endif %}
        <a class="doc-book" href="{% url 'appointments:book' %}">
          <svg class="doc-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>
          Book an Appointment
          <svg class="doc-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
        </a>
      </div>
    </article>
    {% empty %}
    <p class="muted">No doctors are listed yet.</p>
    {% endfor %}
  </div>
</section>

<section class="home-section is-tint" id="services">
  <div class="section-head">
    <h2>Services</h2>
    <p class="section-lead">What you can expect when you visit us.</p>
  </div>
  <div class="grid">
    {% for service in services %}
      <div class="card">
        <span class="card-icon" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/></svg></span>
        <h3>{{ service.name }}</h3><p>{{ service.description }}</p>
      </div>
    {% empty %}
      <p>No services to show yet.</p>
    {% endfor %}
  </div>
</section>

<section class="home-section" id="blog">
  <div class="section-head">
    <h2>Latest news</h2>
    <p class="section-lead">Health news and tips, and updates on the development of our hospital.</p>
  </div>
  <div class="grid">
    {% for post in recent_posts %}
      <div class="card post-card">
        {% if post.image %}
          <a class="post-cover-link" href="{% url 'website:blog_detail' post.slug %}" tabindex="-1" aria-hidden="true"><img class="post-cover" src="{{ post.image.url }}" alt="" loading="lazy"></a>
        {% else %}
          <div class="post-cover post-cover-empty" aria-hidden="true"></div>
        {% endif %}
        <div class="post-body">
          <p class="meta">{{ post.get_category_display }} &middot; {{ post.published_at|date:"j F Y" }}</p>
          <h3><a href="{% url 'website:blog_detail' post.slug %}">{{ post.title }}</a></h3>
          <p>{{ post.summary }}</p>
        </div>
      </div>
    {% empty %}
      <p>No posts yet.</p>
    {% endfor %}
  </div>
  {% if recent_posts %}<p class="section-more"><a class="btn btn-sm btn-ghost" href="{% url 'website:blog' %}">All posts</a></p>{% endif %}
</section>

<section class="home-section is-tint" id="contact">
  <div class="section-head">
    <h2>Contact hospital management</h2>
    <p class="section-lead">Ask for help or information, or send us feedback. Our staff will reply by email. For an emergency, call the emergency number or come straight to the hospital; do not use this form.</p>
  </div>
  <div class="contact-layout">
    <div>
      <form method="post" action="{% url 'website:contact' %}#contact" class="contact" novalidate>
        {% csrf_token %}
        {% if form.non_field_errors %}<div class="msg error">{{ form.non_field_errors }}</div>{% endif %}
        {% for field in form.visible_fields %}
          {% if field.name == "company" %}
            <div class="hp" aria-hidden="true">{{ field.label_tag }} {{ field }}</div>
          {% else %}
            <p>{{ field.label_tag }} {{ field }}{{ field.errors }}</p>
          {% endif %}
        {% endfor %}
        <p class="meta">We use your details only to reply to you. Please do not send medical records or test results here.</p>
        <button class="btn" type="submit">Send</button>
      </form>
    </div>
    <div class="contact-info">
      <h3>Get in touch</h3>
      {% if site.address %}<p><strong>Address</strong><br>{{ site.address|linebreaksbr }}</p>{% endif %}
      {% if site.phone %}<p><strong>Phone</strong><br>{{ site.phone }}</p>{% endif %}
      {% if site.email %}<p><strong>Email</strong><br>{{ site.email }}</p>{% endif %}
      {% if site.opening_hours %}<p><strong>Hours</strong><br>{{ site.opening_hours }}</p>{% endif %}
      {% if site.emergency_phone %}<p class="emergency">Emergency: {{ site.emergency_phone }}</p>{% endif %}
    </div>
  </div>
</section>
{% endblock %}
'''

CSS = r'''
/* ===== One-page home v2 (polish) ===== */

/* info bar under the hero */
body.public .quick-bar{position:relative;z-index:2;display:flex;flex-wrap:wrap;align-items:stretch;max-width:1000px;margin:-2.5rem auto 0;background:#fff;border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow-lg);overflow:hidden}
body.public .quick-item{flex:1 1 190px;display:flex;flex-direction:column;justify-content:center;gap:.1rem;padding:1rem 1.5rem;border-right:1px solid var(--line)}
body.public .quick-label{font-size:.82rem;color:var(--muted)}
body.public .quick-item strong{font-size:1.05rem;line-height:1.3;color:var(--ink)}
body.public .quick-emergency strong{color:#be123c}
body.public .quick-bar .quick-book{flex:0 0 auto;align-self:center;margin:.8rem 1rem}

/* sections: rhythm through alternating tinted bands that run edge to edge */
body.public .home-section{padding:3.4rem 0 1.4rem;scroll-margin-top:88px}
body.public .home-section.is-tint{
  margin-inline:calc(50% - 50vw);padding-inline:calc(50vw - 50%);padding-bottom:3.4rem;
  background:linear-gradient(180deg,color-mix(in srgb,var(--accent-b) 8%,#fff),color-mix(in srgb,var(--accent-d) 7%,#fff))}
body.public .home-section:last-child{margin-bottom:-4rem;padding-bottom:5rem}

/* section headings */
body.public .section-head{max-width:64ch;margin:0 0 1.6rem}
body.public .section-head h2{margin:0 0 .5rem;font-size:clamp(1.7rem,1.2rem + 1.6vw,2.25rem);letter-spacing:-.02em;line-height:1.15;color:var(--ink)}
body.public .section-head h2::before{display:none}
body.public .section-head h2::after{content:"";display:block;width:56px;height:4px;margin-top:.7rem;border-radius:4px;background:var(--grad)}
body.public .section-lead{margin:0;color:var(--muted);font-size:1.05rem;line-height:1.6}

/* about */
body.public #about .article{max-width:860px;padding:1.8rem 2rem;border-left:5px solid var(--accent-a);font-size:1.06rem}

/* department and service cards */
body.public .home-section .grid>.card:not(.post-card){padding:1.5rem 1.4rem;border-top:0;background:#fff}
body.public .home-section .grid>.card:not(.post-card) h3{margin:0 0 .4rem;font-size:1.15rem;color:var(--ink)}
body.public .home-section .grid>.card:not(.post-card) p{margin:0;color:var(--muted);line-height:1.6}
body.public .card-icon{display:grid;place-items:center;width:46px;height:46px;margin-bottom:.95rem;border-radius:14px;background:var(--grad);color:#fff;box-shadow:0 8px 18px var(--glow)}
body.public .card-icon svg{display:block}

/* doctor profile card */
body.public .doc-profile{grid-template-columns:minmax(180px,300px) 1fr;gap:1.6rem 2.4rem;padding:1.4rem;background:#fff;border:1px solid var(--line);border-radius:24px;box-shadow:var(--shadow)}
body.public .doc-photo{border-radius:18px;box-shadow:none}
body.public .home-section .doc-list{padding-top:.4rem}

/* contact */
body.public .contact-layout{grid-template-columns:1.4fr 1fr;gap:1.8rem}
body.public form.contact{padding:1.8rem}
body.public .contact-info{padding:1.8rem;border:0;color:#d9f3f7;background:linear-gradient(165deg,#062f3f,#0a5871 50%,#0b7e94);box-shadow:var(--shadow-lg)}
body.public .contact-info h3{margin:0 0 1rem;font-size:1.25rem;color:#fff}
body.public .contact-info p{color:#cdeaf0}
body.public .contact-info strong{color:#fff}
body.public .contact-info .emergency{background:rgba(225,29,72,.28);color:#ffe3e8;border-color:rgba(255,140,160,.5)}

@media (max-width:860px){
  body.public .quick-bar{margin-inline:0;border-radius:16px}
  body.public .quick-item{border-right:0;border-bottom:1px solid var(--line)}
  body.public .quick-bar .quick-book{flex:1 1 100%;margin:.9rem 1rem}
  body.public .home-section{padding-top:2.6rem}
  body.public #about .article{padding:1.4rem 1.3rem}
  body.public .contact-layout{grid-template-columns:1fr}
}
'''

if not os.path.exists(HOME) or not os.path.exists(CSS_PATH):
    sys.exit("Could not find " + HOME + " or " + CSS_PATH + ". Is this the project folder?")
if not os.path.exists(HOME + ".v1"):
    shutil.copyfile(HOME, HOME + ".v1")
open(HOME, "w", encoding="utf-8", newline="\n").write(HOME_HTML)
print("Replaced", HOME)

text = open(CSS_PATH, encoding="utf-8").read()
if MARK in text:                       # re-run: replace the old v2 block
    text = text[:text.index(MARK)].rstrip() + "\n"
elif not text.endswith("\n"):
    text += "\n"
open(CSS_PATH, "w", encoding="utf-8", newline="\n").write(text + CSS)
print("Styles installed in", CSS_PATH)
print("Done. Press Ctrl+F5 on the home page (restart the server only if it does not change).")
