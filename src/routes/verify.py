"""Public pass-verification pages — what the QR codes on gate/transport passes
point to. A guard scans the QR, opens this page, and sees VALID / EXPIRED /
INVALID at a glance.

Read-only and unauthenticated: the (unguessable, UUID) pass_id is the capability.
pass_id is globally unique across schools, so no tenant context is needed — the
lookup is by pass_id and the school/student come from the matched record.
"""
import datetime
import html

from flask import Blueprint, request, Response

from utils.database import init_db, GatePass, TransportPass, StudentContact, GatePassScan

verify_bp = Blueprint("verify", __name__)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _fmt(dt):
    return dt.strftime("%d %b %Y") if dt else "—"


def _student_name(session, student_id):
    c = session.query(StudentContact).filter(StudentContact.student_id == student_id).first()
    if c:
        return " ".join(p for p in [c.firstname, c.lastname] if p) or student_id
    return student_id


def _page(status, color, emoji, title, rows):
    body_rows = "".join(
        f'<tr><td class="l">{html.escape(str(l))}</td><td>{html.escape(str(v))}</td></tr>'
        for l, v in rows
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;
        background:#f4f6f8;color:#1f2933}}
  .card{{max-width:430px;margin:32px auto;background:#fff;border-radius:16px;
         box-shadow:0 6px 28px rgba(0,0,0,.08);overflow:hidden}}
  .hd{{background:{color};color:#fff;padding:30px 20px;text-align:center}}
  .hd .e{{font-size:52px;line-height:1}}
  .hd h1{{margin:10px 0 0;font-size:23px;letter-spacing:.5px}}
  .bd{{padding:18px 20px}}
  table{{width:100%;border-collapse:collapse;font-size:15px}}
  td{{padding:10px 4px;border-bottom:1px solid #eef1f4;vertical-align:top}}
  td.l{{color:#7b8794;width:44%}}
  tr:last-child td{{border-bottom:none}}
  .ft{{padding:14px 20px;color:#9aa5b1;font-size:12px;text-align:center;border-top:1px solid #eef1f4}}
</style></head>
<body><div class="card">
  <div class="hd"><div class="e">{emoji}</div><h1>{html.escape(status)}</h1></div>
  <div class="bd"><table>{body_rows}</table></div>
  <div class="ft">Shining Smiles College · automated pass verification</div>
</div></body></html>"""


@verify_bp.get("/verify-gatepass")
def verify_gatepass():
    pass_id = (request.args.get("pass_id") or "").strip()
    scanned_by = (request.args.get("whatsapp_number") or "").strip() or None
    session = None
    try:
        session = init_db()
        gp = session.query(GatePass).filter(GatePass.pass_id == pass_id).first() if pass_id else None
        if not gp:
            return Response(_page("INVALID PASS", "#c0392b", "❌", "Gate Pass — Invalid",
                                  [("Pass ID", pass_id or "—"), ("Result", "Not found")]),
                            status=404, mimetype="text/html")

        # Best-effort scan audit row (never block the result on it).
        try:
            session.add(GatePassScan(school_id=gp.school_id, pass_id=pass_id, scanned_at=_now(),
                                     scanned_by_number=scanned_by, matched_registered_number=False))
            session.commit()
        except Exception:
            session.rollback()

        name = _student_name(session, gp.student_id)
        rows = [("Student", name), ("Student ID", gp.student_id), ("Pass ID", pass_id),
                ("Issued", _fmt(gp.issued_date))]
        if gp.expiry_date and gp.expiry_date < _now():
            rows.append(("Expired", _fmt(gp.expiry_date)))
            return Response(_page("EXPIRED", "#e67e22", "⏰", "Gate Pass — Expired", rows),
                            status=200, mimetype="text/html")
        rows.append(("Valid until", _fmt(gp.expiry_date)))
        return Response(_page("VALID", "#1e8449", "✅", "Gate Pass — Valid", rows),
                        status=200, mimetype="text/html")
    finally:
        if session:
            session.close()


@verify_bp.get("/verify-transport-pass")
def verify_transport_pass():
    pass_id = (request.args.get("pass_id") or "").strip()
    session = None
    try:
        session = init_db()
        tp = session.query(TransportPass).filter(TransportPass.pass_id == pass_id).first() if pass_id else None
        if not tp:
            return Response(_page("INVALID PASS", "#c0392b", "❌", "Transport Pass — Invalid",
                                  [("Pass ID", pass_id or "—"), ("Result", "Not found")]),
                            status=404, mimetype="text/html")

        name = _student_name(session, tp.student_id)
        rows = [("Student", name), ("Student ID", tp.student_id), ("Pass ID", pass_id),
                ("Route", f"{tp.route_type} · {tp.service_type}"), ("Term", tp.term),
                ("Issued", _fmt(tp.issued_date))]
        expired = (tp.expiry_date and tp.expiry_date < _now()) or (tp.status and tp.status != "active")
        if expired:
            rows.append(("Expired", _fmt(tp.expiry_date)))
            return Response(_page("EXPIRED", "#e67e22", "⏰", "Transport Pass — Expired", rows),
                            status=200, mimetype="text/html")
        rows.append(("Valid until", _fmt(tp.expiry_date)))
        return Response(_page("VALID", "#1e8449", "✅", "Transport Pass — Valid", rows),
                        status=200, mimetype="text/html")
    finally:
        if session:
            session.close()
