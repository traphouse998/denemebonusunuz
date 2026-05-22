import os
import hashlib
import datetime
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


class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    logo_url = db.Column(db.String(300), default="")
    bonus_text = db.Column(db.String(200), nullable=False)
    promo_kod = db.Column(db.String(50), default="")
    affiliate_link = db.Column(db.String(300), nullable=False)
    kategori = db.Column(db.String(50), default="onerilen")  # vip / onerilen / yeni
    aktif = db.Column(db.Boolean, default=True)
    sira = db.Column(db.Integer, default=0)
    aciklama = db.Column(db.Text, default="")

    def badge_label(self):
        return {"vip": "⭐ VIP", "onerilen": "✓ ÖNERİLEN", "yeni": "🆕 YENİ"}.get(self.kategori, "")

    def toplam_tiklanma(self):
        return Click.query.filter_by(site_id=self.id).count()


class Click(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("site.id"), nullable=False)
    tarih = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    ip_hash = db.Column(db.String(64), default="")
    referer = db.Column(db.String(500), default="")
    cihaz = db.Column(db.String(20), default="")


def get_device(ua):
    ua = ua.lower()
    if any(x in ua for x in ["mobile", "android", "iphone"]):
        return "mobil"
    elif "tablet" in ua or "ipad" in ua:
        return "tablet"
    return "masaustu"


# ─── Ana Sayfa ───────────────────────────────────────────────
@app.route("/")
def index():
    vip_sites = Site.query.filter_by(aktif=True, kategori="vip").order_by(Site.sira).all()
    onerilen_sites = Site.query.filter_by(aktif=True, kategori="onerilen").order_by(Site.sira).all()
    yeni_sites = Site.query.filter_by(aktif=True, kategori="yeni").order_by(Site.sira).all()
    return render_template("index.html",
                           vip_sites=vip_sites,
                           onerilen_sites=onerilen_sites,
                           yeni_sites=yeni_sites)


# ─── Click Tracking ──────────────────────────────────────────
@app.route("/git/<int:site_id>")
def git(site_id):
    site = Site.query.get_or_404(site_id)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    click = Click(
        site_id=site.id,
        ip_hash=hashlib.sha256(ip.encode()).hexdigest(),
        referer=request.referrer or "",
        cihaz=get_device(request.user_agent.string)
    )
    db.session.add(click)
    db.session.commit()
    return redirect(site.affiliate_link)


# ─── Admin ───────────────────────────────────────────────────
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
    return render_template("admin_panel.html", sites=sites, total_clicks=total_clicks)


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


# ─── Statik Sayfalar ─────────────────────────────────────────
@app.route("/gizlilik")
def gizlilik():
    return render_template("gizlilik.html")

@app.route("/iletisim")
def iletisim():
    return render_template("iletisim.html")


# ─── Seed Data ───────────────────────────────────────────────
@app.route("/admin/seed")
def seed():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    if Site.query.count() > 0:
        flash("Veriler zaten mevcut")
        return redirect(url_for("admin_panel"))
    sites_data = [
        {"name": "Betbom", "bonus_text": "250 Freespin + 1000 TL Çekim İmkânı", "promo_kod": "BETBOM500",
         "affiliate_link": "https://www.denemebonuscuyuz.com", "kategori": "vip", "sira": 1,
         "logo_url": "/static/images/betbom.png",
         "aciklama": "Sweet Bonanza'da geçerli 250 deneme freespin! Bizzat test ettim, anında ödüyor."},
        {"name": "Atlasbet", "bonus_text": "Sweet Bonanza 2500x — Deneme Bonusu", "promo_kod": "ATLAS300",
         "affiliate_link": "https://www.denemebonuscuyuz.com", "kategori": "vip", "sira": 2,
         "logo_url": "/static/images/atlasbet-bonus.webp",
         "aciklama": "Pragmatic Play'in en popüler slotu Atlasbet'te. Çevrimsiz freespin fırsatı."},
        {"name": "Bahisfair", "bonus_text": "Sınırsız Kazanç + Freespin Satın Alma", "promo_kod": "FAIR200",
         "affiliate_link": "https://www.denemebonuscuyuz.com", "kategori": "onerilen", "sira": 3,
         "logo_url": "/static/images/bahisfair-bonus.webp",
         "aciklama": "26 yıldır Avrupa ve Türkiye'nin sektör lideri. Günlük 50 Milyon TL çekim imkânı."},
        {"name": "Betzula", "bonus_text": "500 Freespin Deneme Bonusu", "promo_kod": "ZULA500",
         "affiliate_link": "https://www.bedavaspin.com", "kategori": "onerilen", "sira": 4,
         "logo_url": "/static/images/betzula-bonus.webp",
         "aciklama": "Yeni üyelere özel yatırım şartsız 500 freespin! Slot oyunları devasa seçenek."},
        {"name": "Luxbet", "bonus_text": "250 TL Deneme + 30 Freespin", "promo_kod": "LUX250",
         "affiliate_link": "https://www.denemebonuscuyuz.com", "kategori": "onerilen", "sira": 5,
         "logo_url": "/static/images/luxbet-bonus.webp",
         "aciklama": "Premium site, VIP müşteri desteği. Freespin kazançları anında hesaba geçiyor."},
        {"name": "Gameofbet", "bonus_text": "100 TL Deneme + 20 Freespin", "promo_kod": "GOB100",
         "affiliate_link": "https://www.bedavaspin.com", "kategori": "yeni", "sira": 6,
         "logo_url": "/static/images/gameofbet-bonus.webp",
         "aciklama": "Yeni açılan site, agresif bonus kampanyaları. Kayıp iadesi %15."},
        {"name": "Zenbet", "bonus_text": "175 TL + 35 Freespin", "promo_kod": "ZEN175",
         "affiliate_link": "https://www.bedavaspin.com", "kategori": "yeni", "sira": 7,
         "logo_url": "/static/images/zenbet-bonus.webp",
         "aciklama": "Yeni üyelere özel hoşgeldin paketi. Minimum yatırım 50 TL."},
    ]
    for s in sites_data:
        db.session.add(Site(**s))
    db.session.commit()
    flash("Örnek siteler eklendi")
    return redirect(url_for("admin_panel"))


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=False)
