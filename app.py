import os
import json
import hashlib
import datetime
import threading
import urllib.request as _urllib_req
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "denemebonusunuz-secret-2026")

db_url = os.getenv("DATABASE_URL", "sqlite:///sites.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

HEDEF_URL = "https://www.denemebonuscuyuz.com"


# ─── MODELLER ──────────────────────────────────────────────────────────────

class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    logo_url = db.Column(db.String(300), default="")
    bonus_text = db.Column(db.String(200), nullable=False)
    promo_kod = db.Column(db.String(50), default="")
    affiliate_link = db.Column(db.String(300), nullable=False)
    kategori = db.Column(db.String(50), default="onerilen")
    aktif = db.Column(db.Boolean, default=True)
    sira = db.Column(db.Integer, default=0)
    aciklama = db.Column(db.Text, default="")

    def badge_label(self):
        return {"vip": "⭐ VIP", "onerilen": "✓ ÖNERİLEN", "yeni": "🆕 YENİ"}.get(self.kategori, "")

    def toplam_tiklanma(self):
        return Click.query.filter_by(site_id=self.id).count()


class Click(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("site.id"), nullable=True)
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    kaynak = db.Column(db.String(100), default="slot")    # slot / site / admin
    user_agent = db.Column(db.String(300), default="")
    ip_hash = db.Column(db.String(64), default="")        # SHA256(IP)
    ip_kismi = db.Column(db.String(20), default="")       # 85.123.45.xxx
    referer = db.Column(db.String(500), default="")
    cihaz = db.Column(db.String(20), default="")          # masaustu / mobil / tablet
    sehir = db.Column(db.String(100), default="")
    ulke = db.Column(db.String(100), default="")


# ─── DB KURULUM + MIGRATION ───────────────────────────────────────────────

with app.app_context():
    db.create_all()
    try:
        import sqlalchemy as _sa
        with db.engine.connect() as _conn:
            _inspector = _sa.inspect(db.engine)
            if "click" in _inspector.get_table_names():
                _click_cols = [c["name"] for c in _inspector.get_columns("click")]
                for _col, _typ in [
                    ("kaynak",     "VARCHAR(100)"),
                    ("user_agent", "VARCHAR(300)"),
                    ("ip_hash",    "VARCHAR(64)"),
                    ("ip_kismi",   "VARCHAR(20)"),
                    ("referer",    "VARCHAR(500)"),
                    ("cihaz",      "VARCHAR(20)"),
                    ("sehir",      "VARCHAR(100)"),
                    ("ulke",       "VARCHAR(100)"),
                ]:
                    if _col not in _click_cols:
                        _conn.execute(_sa.text(f"ALTER TABLE click ADD COLUMN {_col} {_typ} DEFAULT ''"))
                        _conn.commit()
            if "site" in _inspector.get_table_names():
                _site_cols = [c["name"] for c in _inspector.get_columns("site")]
                for _col, _typ in [
                    ("promo_kod", "VARCHAR(50)"),
                    ("aciklama",  "TEXT"),
                ]:
                    if _col not in _site_cols:
                        _conn.execute(_sa.text(f"ALTER TABLE site ADD COLUMN {_col} {_typ} DEFAULT ''"))
                        _conn.commit()
    except Exception as _e:
        print(f"Migration uyarısı: {_e}")


# ─── YARDIMCI FONKSİYONLAR ───────────────────────────────────────────────

def hash_ip(ip):
    return hashlib.sha256((ip or "").encode()).hexdigest()[:16]


def _ip_kismi(ip):
    """IP'nin son oktetini gizle: 85.123.45.67 → 85.123.45.xxx"""
    try:
        parts = (ip or "").split(".")
        if len(parts) == 4:
            return ".".join(parts[:3]) + ".xxx"
    except Exception:
        pass
    return ""


def detect_device(ua_string):
    ua = (ua_string or "").lower()
    if any(x in ua for x in ["ipad", "tablet", "kindle"]):
        return "tablet"
    if any(x in ua for x in ["mobile", "android", "iphone", "windows phone"]):
        return "mobil"
    return "masaustu"


def geolocate_ip(ip):
    """ip-api.com ücretsiz geolocation (lokal IP'leri atlar)"""
    try:
        if not ip or ip.startswith(("127.", "10.", "192.168.", "::1")):
            return "", ""
        url = f"http://ip-api.com/json/{ip}?fields=status,city,country&lang=tr"
        with _urllib_req.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                return data.get("city", ""), data.get("country", "")
    except Exception:
        pass
    return "", ""


def log_click(kaynak="slot", site_id=None):
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        ua = request.user_agent.string if request.user_agent else ""
        click = Click(
            site_id=site_id,
            kaynak=kaynak,
            user_agent=ua[:300],
            ip_hash=hash_ip(ip),
            ip_kismi=_ip_kismi(ip),
            referer=request.referrer[:500] if request.referrer else "",
            cihaz=detect_device(ua),
        )
        db.session.add(click)
        db.session.commit()
        click_id = click.id

        # Geolocation arka planda
        def _geo():
            try:
                sehir, ulke = geolocate_ip(ip)
                if sehir or ulke:
                    with app.app_context():
                        c = Click.query.get(click_id)
                        if c:
                            c.sehir = sehir
                            c.ulke = ulke
                            db.session.commit()
            except Exception:
                pass
        threading.Thread(target=_geo, daemon=True).start()

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"log_click hata: {e}")


# ─── ANA SAYFA (Slot Makinesi) ────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── SLOT MAKİNESİ YÖNLENDİRME ───────────────────────────────────────────

@app.route("/slot-git")
def slot_git():
    """Slot makinesi kazanma → tıklama kaydet → denemebonuscuyuz.com"""
    log_click(kaynak="slot")
    return redirect(HEDEF_URL)


# ─── SİTE BAZLI YÖNLENDİRME (eski sistem) ────────────────────────────────

@app.route("/git/<int:site_id>")
def git(site_id):
    site = Site.query.get_or_404(site_id)
    log_click(kaynak=request.args.get("k", "site"), site_id=site.id)
    return redirect(site.affiliate_link)


# ─── ADMIN GİRİŞ ─────────────────────────────────────────────────────────

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_panel"))
        flash("Hatalı şifre")
    return render_template("admin_login.html")


@app.route("/admin/panel")
def admin_panel():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    sites = Site.query.order_by(Site.kategori, Site.sira).all()
    total_clicks = Click.query.count()
    slot_clicks  = Click.query.filter_by(kaynak="slot").count()
    return render_template("admin_panel.html", sites=sites,
                           total_clicks=total_clicks, slot_clicks=slot_clicks)


# ─── ADMIN İSTATİSTİKLER ─────────────────────────────────────────────────

@app.route("/admin/istatistikler")
def admin_istatistikler():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    from sqlalchemy import func, distinct, extract
    from urllib.parse import urlparse as _up

    now = datetime.datetime.utcnow()
    bugun = now.date()
    dt_bugun = datetime.datetime(bugun.year, bugun.month, bugun.day)
    dt_hafta = now - datetime.timedelta(days=7)
    dt_30    = now - datetime.timedelta(days=30)

    # ── Global özet ──────────────────────────────────────────────────────
    global_bugun  = Click.query.filter(Click.tarih >= dt_bugun).count()
    global_hafta  = Click.query.filter(Click.tarih >= dt_hafta).count()
    global_toplam = Click.query.count()
    slot_toplam   = Click.query.filter_by(kaynak="slot").count()

    # ── Slot vs diğer (son 30 gün) ───────────────────────────────────────
    kaynak_rows = db.session.query(
        Click.kaynak, func.count(Click.id)
    ).filter(Click.tarih >= dt_30).group_by(Click.kaynak).all()
    kaynak_data = {(r[0] or "slot"): r[1] for r in kaynak_rows}

    # ── Cihaz dağılımı ───────────────────────────────────────────────────
    cihaz_rows = db.session.query(
        Click.cihaz, func.count(Click.id)
    ).filter(Click.tarih >= dt_30, Click.cihaz != "").group_by(Click.cihaz).all()
    cihaz_data = {r[0]: r[1] for r in cihaz_rows}

    # ── Son 14 günlük grafik ──────────────────────────────────────────────
    gunluk = []
    for i in range(13, -1, -1):
        d = bugun - datetime.timedelta(days=i)
        d_start = datetime.datetime(d.year, d.month, d.day)
        d_end   = d_start + datetime.timedelta(days=1)
        c = Click.query.filter(Click.tarih >= d_start, Click.tarih < d_end).count()
        gunluk.append({"gun": d.strftime("%d/%m"), "sayi": c})

    # ── Saatlik trafik ───────────────────────────────────────────────────
    saat_rows = db.session.query(
        extract('hour', Click.tarih).label('saat'), func.count(Click.id)
    ).filter(Click.tarih >= dt_30).group_by('saat').order_by('saat').all()
    saat_data  = {int(r[0]): r[1] for r in saat_rows}
    saat_liste = [saat_data.get(h, 0) for h in range(24)]

    # ── Şehir & ülke ─────────────────────────────────────────────────────
    sehir_rows = db.session.query(
        Click.sehir, func.count(Click.id).label("c")
    ).filter(Click.tarih >= dt_30, Click.sehir != "", Click.sehir.isnot(None)
    ).group_by(Click.sehir).order_by(func.count(Click.id).desc()).limit(10).all()
    top_sehirler = [(r[0], r[1]) for r in sehir_rows]

    ulke_rows = db.session.query(
        Click.ulke, func.count(Click.id).label("c")
    ).filter(Click.tarih >= dt_30, Click.ulke != "", Click.ulke.isnot(None)
    ).group_by(Click.ulke).order_by(func.count(Click.id).desc()).limit(10).all()
    top_ulkeler = [(r[0], r[1]) for r in ulke_rows]

    # ── Top referer domainleri ────────────────────────────────────────────
    ref_rows = db.session.query(
        Click.referer, func.count(Click.id).label("c")
    ).filter(Click.tarih >= dt_30, Click.referer != "").group_by(
        Click.referer
    ).order_by(func.count(Click.id).desc()).limit(100).all()
    domain_counts = {}
    for ref, cnt in ref_rows:
        try:
            parsed = _up(ref)
            domain = parsed.netloc or parsed.path.split("/")[0]
            domain = domain.replace("www.", "").lower()
        except Exception:
            domain = ref[:40]
        domain_counts[domain] = domain_counts.get(domain, 0) + cnt
    top_referrers = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # ── Son tıklamalar ────────────────────────────────────────────────────
    son_tiklamalar = Click.query.order_by(Click.tarih.desc()).limit(20).all()

    return render_template(
        "admin_istatistikler.html",
        global_bugun=global_bugun, global_hafta=global_hafta,
        global_toplam=global_toplam, slot_toplam=slot_toplam,
        kaynak_data=kaynak_data, cihaz_data=cihaz_data,
        gunluk=gunluk, saat_liste=saat_liste,
        top_sehirler=top_sehirler, top_ulkeler=top_ulkeler,
        top_referrers=top_referrers,
        son_tiklamalar=son_tiklamalar,
    )


# ─── ADMIN TIK LAMA LİSTESİ ──────────────────────────────────────────────

@app.route("/admin/tiklama-listesi")
def admin_tiklama_listesi():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    sayfa = request.args.get("sayfa", 1, type=int)
    per_page = 50
    q = Click.query.order_by(Click.tarih.desc())
    toplam = q.count()
    tiklamalar = q.offset((sayfa - 1) * per_page).limit(per_page).all()
    return render_template(
        "admin_tiklama_listesi.html",
        tiklamalar=tiklamalar,
        sayfa=sayfa, per_page=per_page, toplam=toplam,
    )


# ─── ADMIN SİTE YÖNETİMİ ─────────────────────────────────────────────────

@app.route("/admin/site/add", methods=["POST"])
def admin_add_site():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    site = Site(
        name=request.form["name"],
        bonus_text=request.form["bonus_text"],
        promo_kod=request.form.get("promo_kod", ""),
        affiliate_link=request.form["affiliate_link"],
        logo_url=request.form.get("logo_url", ""),
        kategori=request.form.get("kategori", "onerilen"),
        sira=int(request.form.get("sira", 0)),
        aciklama=request.form.get("aciklama", ""),
    )
    db.session.add(site)
    db.session.commit()
    flash(f"{site.name} eklendi")
    return redirect(url_for("admin_panel"))


@app.route("/admin/site/edit/<int:site_id>", methods=["GET", "POST"])
def admin_edit_site(site_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    site = Site.query.get_or_404(site_id)
    if request.method == "POST":
        site.name = request.form["name"]
        site.bonus_text = request.form["bonus_text"]
        site.promo_kod = request.form.get("promo_kod", "")
        site.affiliate_link = request.form["affiliate_link"]
        site.logo_url = request.form.get("logo_url", "")
        site.kategori = request.form.get("kategori", "onerilen")
        site.sira = int(request.form.get("sira", 0))
        site.aciklama = request.form.get("aciklama", "")
        site.aktif = "aktif" in request.form
        db.session.commit()
        flash(f"{site.name} güncellendi")
        return redirect(url_for("admin_panel"))
    return render_template("admin_edit.html", site=site)


@app.route("/admin/site/delete/<int:site_id>", methods=["POST"])
def admin_delete_site(site_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    site = Site.query.get_or_404(site_id)
    Click.query.filter_by(site_id=site_id).delete()
    db.session.delete(site)
    db.session.commit()
    flash(f"{site.name} silindi")
    return redirect(url_for("admin_panel"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


# ─── STATİK SAYFALAR ─────────────────────────────────────────────────────

@app.route("/gizlilik")
def gizlilik():
    return render_template("gizlilik.html")


@app.route("/iletisim")
def iletisim():
    return render_template("iletisim.html")


if __name__ == "__main__":
    app.run(debug=False)
