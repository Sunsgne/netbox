"""ZENLENET operations console."""

from __future__ import annotations

import csv
import hmac
import io
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.billing import generate_invoices, order_lines
from app.content import (
    DC_TYPES,
    INVOICE_STATUS,
    ORDER_STATUS,
    PRODUCT_LABELS,
    REASONS,
    ROLE_LABELS,
    STATUS_LABELS,
    TICKET_STEPS,
    TICKET_TYPES,
)
from app.db import SessionLocal, init_db, price_map, verify_password
from app.models import (
    Circuit,
    Customer,
    Invoice,
    IpRecord,
    NoticeTemplate,
    Price,
    ServiceOrder,
    SupplierReturn,
    Ticket,
    TicketEvent,
    User,
    VxlanLink,
)
from app.parsing import (
    classify_customer,
    clean_remark,
    extract_ips,
    extract_v6,
    is_private_v4,
    render_notice,
)

PAGE_SIZE = 40
OPEN_TICKETS = {"draft", "review", "notify", "notified", "executing", "verify"}
STEP_LABELS = dict(TICKET_STEPS)
STEP_LABELS["cancelled"] = "已取消"
TYPE_LABELS = {code: label for code, label, _tpl in TICKET_TYPES}
TYPE_TEMPLATE = {code: tpl for code, _label, tpl in TICKET_TYPES}
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals.update(
    STATUS_LABELS=STATUS_LABELS,
    PRODUCT_LABELS=PRODUCT_LABELS,
    ORDER_STATUS=ORDER_STATUS,
    INVOICE_STATUS=INVOICE_STATUS,
    ROLE_LABELS=ROLE_LABELS,
    STEP_LABELS=STEP_LABELS,
    TYPE_LABELS=TYPE_LABELS,
    TICKET_STEPS=TICKET_STEPS,
)


def money(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


templates.env.filters["money"] = money


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path in {"/login", "/healthz"}:
        return await call_next(request)
    if not request.session.get("uid"):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "zenlenet-dev-secret"),
    https_only=os.environ.get("SESSION_HTTPS_ONLY", "0") == "1",
    same_site="lax",
    max_age=60 * 60 * 14,
)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf"] = token
    return token


def csrf_ok(request: Request, token: str) -> bool:
    expected = request.session.get("csrf") or ""
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, token)


def flash(request: Request, message: str) -> None:
    request.session["flash"] = message


def keep(request: Request, **updates) -> str:
    data = dict(request.query_params)
    data.pop("page", None)
    for key, value in updates.items():
        if value is None or value == "":
            data.pop(key, None)
        else:
            data[key] = str(value)
    return urlencode(data)


def render(request: Request, name: str, **extra):
    extra["request"] = request
    extra.setdefault("flash", request.session.pop("flash", None))
    extra.setdefault("csrf", csrf_token(request))
    extra.setdefault("username", request.session.get("user", ""))
    extra["keep"] = lambda **kwargs: keep(request, **kwargs)
    return templates.TemplateResponse(request, name, extra)


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def customer_by_name(db: Session, name: str) -> Customer | None:
    kind, cleaned = classify_customer(name)
    if kind not in {"customer", "hold"} or not cleaned:
        return None
    found = db.scalar(select(Customer).where(Customer.name == cleaned))
    if found:
        return found
    found = Customer(name=cleaned, kind="external", status="active")
    db.add(found)
    db.flush()
    return found


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("uid"):
        return redirect("/")
    return render(request, "login.html", error="")


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not csrf_ok(request, csrf):
        return render(request, "login.html", error="页面已过期，请再试一次。")
    user = db.scalar(select(User).where(User.username == username.strip()))
    if not user or not verify_password(password, user.password_hash):
        return render(request, "login.html", error="账号或密码不对。")
    request.session["uid"] = user.id
    request.session["user"] = user.username
    return redirect("/")


@app.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    if csrf_ok(request, csrf):
        request.session.clear()
    return redirect("/login")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    status_rows = db.execute(select(IpRecord.status, func.count()).group_by(IpRecord.status)).all()
    by_status = {status: count for status, count in status_rows}
    address_total = sum(by_status.values())
    customers = db.scalar(select(func.count()).select_from(Customer)) or 0
    active_customers = db.scalar(select(func.count()).select_from(Customer).where(Customer.status == "active")) or 0
    open_tickets = db.scalar(select(func.count()).select_from(Ticket).where(Ticket.status.in_(OPEN_TICKETS))) or 0
    prices = price_map(db)
    active_orders = db.scalars(select(ServiceOrder).where(ServiceOrder.status == "active")).all()
    mrr = sum(line["amount"] for line in order_lines(active_orders, prices))
    soon = date.today() + timedelta(days=45)
    expiring = db.scalars(
        select(IpRecord)
        .options(selectinload(IpRecord.customer))
        .where(IpRecord.expires_on.is_not(None), IpRecord.expires_on <= soon)
        .order_by(IpRecord.expires_on)
        .limit(8)
    ).all()
    tickets = db.scalars(
        select(Ticket).options(selectinload(Ticket.customer)).where(Ticket.status.in_(OPEN_TICKETS)).order_by(Ticket.id.desc()).limit(6)
    ).all()
    pop_rows = db.execute(select(IpRecord.pop, IpRecord.status, func.count()).group_by(IpRecord.pop, IpRecord.status)).all()
    pops: dict[str, dict] = {}
    for pop, status, count in pop_rows:
        bucket = pops.setdefault(pop or "未标注", {"pop": pop or "未标注", "total": 0, "allocated": 0})
        bucket["total"] += count
        if status == "allocated":
            bucket["allocated"] += count
    pop_bars = sorted(pops.values(), key=lambda item: item["total"], reverse=True)[:8]
    for item in pop_bars:
        item["pct"] = round(100 * item["allocated"] / item["total"]) if item["total"] else 0
    return render(
        request,
        "dashboard.html",
        by_status=by_status,
        address_total=address_total,
        customers=customers,
        active_customers=active_customers,
        open_tickets=open_tickets,
        mrr=mrr,
        expiring=expiring,
        tickets=tickets,
        pop_bars=pop_bars,
        today=date.today(),
    )


@app.get("/customers", response_class=HTMLResponse)
def customers(request: Request, q: str = "", status: str = "", page: int = 1, db: Session = Depends(get_db)):
    stmt = select(Customer)
    if q.strip():
        stmt = stmt.where(Customer.name.ilike(f"%{q.strip()}%"))
    if status:
        stmt = stmt.where(Customer.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = max(1, page)
    rows = db.scalars(stmt.order_by(Customer.status, Customer.name).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    stats = {}
    if rows:
        ids = [row.id for row in rows]
        ip_counts = dict(
            db.execute(
                select(IpRecord.customer_id, func.count()).where(IpRecord.customer_id.in_(ids), IpRecord.status == "allocated").group_by(IpRecord.customer_id)
            ).all()
        )
        order_counts = dict(
            db.execute(
                select(ServiceOrder.customer_id, func.count()).where(ServiceOrder.customer_id.in_(ids), ServiceOrder.status == "active").group_by(ServiceOrder.customer_id)
            ).all()
        )
        for row in rows:
            stats[row.id] = {"ips": ip_counts.get(row.id, 0), "orders": order_counts.get(row.id, 0)}
    return render(
        request,
        "customers.html",
        rows=rows,
        stats=stats,
        q=q,
        status=status,
        page=page,
        pages=max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        total=total,
    )


@app.get("/customers/{customer_id}", response_class=HTMLResponse)
def customer_detail(request: Request, customer_id: int, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if not customer:
        return redirect("/customers")
    orders = db.scalars(select(ServiceOrder).where(ServiceOrder.customer_id == customer.id).order_by(ServiceOrder.status, ServiceOrder.id.desc())).all()
    addresses = db.scalars(
        select(IpRecord).where(IpRecord.customer_id == customer.id).order_by(IpRecord.status, IpRecord.pop, IpRecord.address).limit(40)
    ).all()
    address_total = db.scalar(select(func.count()).select_from(IpRecord).where(IpRecord.customer_id == customer.id)) or 0
    invoices = db.scalars(select(Invoice).where(Invoice.customer_id == customer.id).order_by(Invoice.id.desc())).all()
    tickets = db.scalars(select(Ticket).where(Ticket.customer_id == customer.id).order_by(Ticket.id.desc())).all()
    prices = price_map(db)
    mrr = sum(line["amount"] for line in order_lines([order for order in orders if order.status == "active"], prices))
    return render(
        request,
        "customer.html",
        customer=customer,
        orders=orders,
        addresses=addresses,
        address_total=address_total,
        invoices=invoices,
        tickets=tickets,
        mrr=mrr,
        period=date.today().strftime("%Y-%m"),
    )


@app.get("/orders", response_class=HTMLResponse)
def orders(request: Request, q: str = "", product: str = "", status: str = "active", page: int = 1, db: Session = Depends(get_db)):
    stmt = select(ServiceOrder).options(selectinload(ServiceOrder.customer))
    if status:
        stmt = stmt.where(ServiceOrder.status == status)
    if product:
        stmt = stmt.where(ServiceOrder.product == product)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.join(Customer).where(or_(Customer.name.ilike(like), ServiceOrder.pop_code.ilike(like), ServiceOrder.ip_text.ilike(like), ServiceOrder.circuit_no.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    page = max(1, page)
    rows = db.scalars(stmt.order_by(ServiceOrder.id.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    return render(
        request,
        "orders.html",
        rows=rows,
        q=q,
        product=product,
        status=status,
        page=page,
        pages=max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        total=total,
    )


def _ip_query(db: Session, q: str, pop: str, status: str, attr: str, supplier: str, dc_type: str, family: str):
    stmt = select(IpRecord).options(selectinload(IpRecord.customer))
    if family == "6":
        stmt = stmt.where(IpRecord.version == 6)
    elif family == "4":
        stmt = stmt.where(IpRecord.version == 4)
    if pop:
        stmt = stmt.where(IpRecord.pop == pop)
    if status:
        stmt = stmt.where(IpRecord.status == status)
    if attr:
        stmt = stmt.where(IpRecord.net_attr == attr)
    if supplier:
        stmt = stmt.where(IpRecord.supplier == supplier)
    if dc_type:
        stmt = stmt.where(IpRecord.dc_type == dc_type)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.outerjoin(Customer).where(or_(IpRecord.address.ilike(like), IpRecord.remark.ilike(like), Customer.name.ilike(like)))
    return stmt


@app.get("/resources", response_class=HTMLResponse)
def resources(
    request: Request,
    q: str = "",
    pop: str = "",
    status: str = "",
    attr: str = "",
    supplier: str = "",
    dc_type: str = "",
    family: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
):
    stmt = _ip_query(db, q, pop, status, attr, supplier, dc_type, family)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    page = max(1, page)
    rows = db.scalars(stmt.order_by(IpRecord.pop, IpRecord.address, IpRecord.prefixlen).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    pops = [item for item, in db.execute(select(IpRecord.pop).where(IpRecord.pop != "").group_by(IpRecord.pop).order_by(func.count().desc())).all()]
    suppliers = [item for item, in db.execute(select(IpRecord.supplier).where(IpRecord.supplier != "").group_by(IpRecord.supplier).order_by(func.count().desc()).limit(30)).all()]
    names = db.scalars(select(Customer.name).order_by(Customer.name).limit(400)).all()
    return render(
        request,
        "resources.html",
        rows=rows,
        q=q,
        pop=pop,
        status=status,
        attr=attr,
        supplier=supplier,
        dc_type=dc_type,
        family=family,
        page=page,
        pages=max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        total=total,
        pops=pops,
        suppliers=suppliers,
        names=names,
        dc_types=DC_TYPES,
    )


@app.get("/resources/summary", response_class=HTMLResponse)
def resource_summary(request: Request, pop: str = "", db: Session = Depends(get_db)):
    stmt = select(IpRecord)
    if pop:
        stmt = stmt.where(IpRecord.pop == pop)
    buckets: dict[tuple, dict] = {}
    for record in db.scalars(stmt):
        if record.version == 4 and record.prefixlen == 32:
            prefix = ".".join(record.address.split(".")[:3]) + ".0/24"
        else:
            prefix = f"{record.address}/{record.prefixlen}"
        key = (record.pop, prefix)
        bucket = buckets.setdefault(key, {"pop": record.pop, "prefix": prefix, "total": 0, "allocated": 0, "free": 0, "supplier": record.supplier})
        bucket["total"] += 1
        if record.status == "allocated":
            bucket["allocated"] += 1
        elif record.status == "free":
            bucket["free"] += 1
    rows = sorted(buckets.values(), key=lambda item: (item["allocated"], item["total"]), reverse=True)[:200]
    pops = [item for item, in db.execute(select(IpRecord.pop).where(IpRecord.pop != "").group_by(IpRecord.pop).order_by(IpRecord.pop)).all()]
    return render(request, "summary.html", rows=rows, pop=pop, pops=pops)


@app.get("/resources/export")
def export_resources(
    request: Request,
    q: str = "",
    pop: str = "",
    status: str = "",
    attr: str = "",
    supplier: str = "",
    dc_type: str = "",
    family: str = "",
    db: Session = Depends(get_db),
):
    stmt = _ip_query(db, q, pop, status, attr, supplier, dc_type, family)
    rows = db.scalars(stmt.order_by(IpRecord.pop, IpRecord.address).limit(20000)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["地址", "地区", "供应商", "数据中心类型", "网络属性", "资源属性", "状态", "客户", "用途", "到期", "备注"])
    for record in rows:
        writer.writerow([
            record.display,
            record.pop,
            record.supplier,
            record.dc_type,
            record.net_attr,
            ROLE_LABELS.get(record.role, record.role),
            STATUS_LABELS.get(record.status, record.status),
            record.customer.name if record.customer else "",
            record.usage,
            record.expires_on.isoformat() if record.expires_on else "",
            record.remark,
        ])
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=zenlenet-ip.csv"},
    )


@app.post("/resources")
def create_resource(
    request: Request,
    cidr: str = Form(""),
    pop: str = Form(""),
    supplier: str = Form(""),
    role: str = Form("other"),
    net_attr: str = Form("公网"),
    dc_type: str = Form("第三方"),
    customer: str = Form(""),
    remark: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not csrf_ok(request, csrf):
        flash(request, "页面已过期。")
        return redirect("/resources")
    found = extract_ips(cidr) or [(addr, plen) for addr, plen in extract_v6(cidr)]
    if not found or not pop.strip():
        flash(request, "请填写地区，以及合法的 IPv4 / IPv6 地址或网段。")
        return redirect("/resources")
    owner = customer_by_name(db, customer) if customer.strip() else None
    status = "allocated" if owner else "free"
    for address, plen in found[:64]:
        version = 6 if ":" in address else 4
        exists = db.scalar(select(IpRecord).where(IpRecord.version == version, IpRecord.address == address, IpRecord.prefixlen == plen))
        if exists:
            continue
        attr = "内网" if version == 4 and is_private_v4(address) else (net_attr if net_attr in {"公网", "内网"} else "公网")
        db.add(
            IpRecord(
                version=version,
                address=address,
                prefixlen=plen,
                pop=pop.strip()[:80],
                supplier=supplier.strip()[:80],
                customer_id=owner.id if owner else None,
                role=role if role in ROLE_LABELS else "other",
                net_attr=attr,
                dc_type=dc_type if dc_type in DC_TYPES else "第三方",
                status=status,
                remark=clean_remark(remark),
                source="手工",
            )
        )
    db.commit()
    flash(request, "地址已写入资源库。")
    return redirect("/resources")


@app.post("/resources/{record_id}/assign")
def assign_resource(
    request: Request,
    record_id: int,
    customer: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    record = db.get(IpRecord, record_id)
    if not record or not csrf_ok(request, csrf):
        return redirect("/resources")
    owner = customer_by_name(db, customer)
    if not owner:
        flash(request, "没有识别到客户名称。")
        return redirect("/resources")
    record.customer_id = owner.id
    record.status = "allocated"
    db.commit()
    flash(request, f"{record.display} 已分配给 {owner.name}。")
    return redirect("/resources?" + urlencode({"q": record.address}))


@app.post("/resources/{record_id}/release")
def release_resource(request: Request, record_id: int, csrf: str = Form(""), db: Session = Depends(get_db)):
    record = db.get(IpRecord, record_id)
    if record and csrf_ok(request, csrf):
        record.customer_id = None
        record.status = "free"
        record.usage = ""
        db.commit()
        flash(request, f"{record.display} 已回收为未分配。")
    return redirect("/resources")


@app.get("/billing", response_class=HTMLResponse)
def billing(request: Request, db: Session = Depends(get_db)):
    invoices = db.scalars(select(Invoice).options(selectinload(Invoice.customer)).order_by(Invoice.id.desc()).limit(200)).all()
    prices = db.scalars(select(Price).order_by(Price.code)).all()
    return render(request, "billing.html", invoices=invoices, prices=prices, period=date.today().strftime("%Y-%m"))


@app.post("/billing/generate")
def billing_generate(
    request: Request,
    period: str = Form(""),
    customer_id: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not csrf_ok(request, csrf):
        return redirect("/billing")
    if len(period) != 7 or period[4] != "-":
        flash(request, "账期格式应为 YYYY-MM。")
        return redirect("/billing")
    target = int(customer_id) if customer_id.isdigit() else None
    created = generate_invoices(db, period, target)
    db.commit()
    flash(request, f"{period} 已生成 {created} 张草稿账单。" if created else f"{period} 没有新的可出账客户。")
    if target:
        return redirect(f"/customers/{target}")
    return redirect("/billing")


@app.get("/billing/prices", response_class=HTMLResponse)
def prices(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Price).order_by(Price.code)).all()
    return render(request, "prices.html", rows=rows)


@app.post("/billing/prices")
async def prices_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    if not csrf_ok(request, str(form.get("csrf") or "")):
        return redirect("/billing/prices")
    for row in db.scalars(select(Price)):
        raw = form.get(f"amount_{row.code}")
        if raw is None or raw == "":
            continue
        try:
            row.amount = max(0, float(raw))
        except ValueError:
            continue
    db.commit()
    flash(request, "演示价目已更新。已生成的账单不会自动改写。")
    return redirect("/billing/prices")


@app.get("/billing/{invoice_id}", response_class=HTMLResponse)
def invoice_detail(request: Request, invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.scalar(select(Invoice).options(selectinload(Invoice.customer), selectinload(Invoice.lines)).where(Invoice.id == invoice_id))
    if not invoice:
        return redirect("/billing")
    return render(request, "invoice.html", invoice=invoice)


@app.post("/billing/{invoice_id}/status")
def invoice_status(request: Request, invoice_id: int, action: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice or not csrf_ok(request, csrf):
        return redirect("/billing")
    order = ["draft", "confirmed", "sent", "paid"]
    if invoice.status in order:
        index = order.index(invoice.status)
        if action == "next" and index < len(order) - 1:
            invoice.status = order[index + 1]
        elif action == "prev" and index > 0:
            invoice.status = order[index - 1]
    db.commit()
    return redirect(f"/billing/{invoice.id}")


@app.get("/tickets", response_class=HTMLResponse)
def tickets(request: Request, status: str = "", type_code: str = "", db: Session = Depends(get_db)):
    stmt = select(Ticket).options(selectinload(Ticket.customer))
    if status:
        stmt = stmt.where(Ticket.status == status)
    if type_code:
        stmt = stmt.where(Ticket.type_code == type_code)
    rows = db.scalars(stmt.order_by(Ticket.id.desc()).limit(200)).all()
    return render(request, "tickets.html", rows=rows, status=status, type_code=type_code)


@app.get("/tickets/new", response_class=HTMLResponse)
def ticket_new(request: Request, customer_id: int = 0, db: Session = Depends(get_db)):
    customers = db.scalars(select(Customer).where(Customer.status != "churned").order_by(Customer.name)).all()
    start = (datetime.utcnow() + timedelta(hours=8, days=2)).replace(minute=0, second=0, microsecond=0)
    return render(
        request,
        "ticket_form.html",
        customers=customers,
        customer_id=customer_id,
        reasons=REASONS,
        start_value=start.strftime("%Y-%m-%dT%H:%M"),
        end_value=(start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
    )


@app.post("/tickets")
def ticket_create(
    request: Request,
    type_code: str = Form("maintenance"),
    customer_id: str = Form(""),
    pop: str = Form(""),
    impact: str = Form(""),
    reason: str = Form(""),
    duration: str = Form("30分钟"),
    start: str = Form(""),
    end: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if not csrf_ok(request, csrf) or type_code not in TYPE_TEMPLATE:
        return redirect("/tickets")
    window_start = _parse_dt(start)
    window_end = _parse_dt(end)
    customer = db.get(Customer, int(customer_id)) if customer_id.isdigit() else None
    place = pop.strip() or "未指定节点"
    ctx = _notice_ctx(place, impact, reason, duration, window_start, window_end, type_code)
    template = db.get(NoticeTemplate, TYPE_TEMPLATE[type_code])
    subject = render_notice(template.subject if template else "", ctx)
    body = render_notice(template.body if template else "", ctx)
    count = db.scalar(select(func.count()).select_from(Ticket)) or 0
    label = TYPE_LABELS.get(type_code, "维护")
    ticket = Ticket(
        key=f"ZL-{1001 + count}",
        type_code=type_code,
        title=f"{place} {label}" + (f" - {customer.name}" if customer else ""),
        customer_id=customer.id if customer else None,
        pop=place,
        status="draft",
        window_start=window_start,
        window_end=window_end,
        impact=clean_remark(impact) or impact.strip()[:500],
        reason=reason[:120],
        duration=duration[:40] or "30分钟",
        subject=subject,
        body=body,
        assignee=request.session.get("user", "NOC"),
    )
    db.add(ticket)
    db.flush()
    db.add(TicketEvent(ticket_id=ticket.id, author=ticket.assignee, action="创建", body="工单已建立，通知正文可在发出前修改。"))
    db.commit()
    flash(request, f"{ticket.key} 已创建。")
    return redirect(f"/tickets/{ticket.id}")


@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(request: Request, ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.scalar(
        select(Ticket).options(selectinload(Ticket.customer), selectinload(Ticket.events)).where(Ticket.id == ticket_id)
    )
    if not ticket:
        return redirect("/tickets")
    steps = [code for code, _label in TICKET_STEPS]
    index = steps.index(ticket.status) if ticket.status in steps else -1
    return render(request, "ticket.html", ticket=ticket, step_index=index, step_count=len(steps))


@app.post("/tickets/{ticket_id}")
def ticket_update(
    request: Request,
    ticket_id: int,
    action: str = Form("save"),
    subject: str = Form(""),
    body: str = Form(""),
    comment: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    ticket = db.get(Ticket, ticket_id)
    if not ticket or not csrf_ok(request, csrf):
        return redirect("/tickets")
    ticket.subject = subject.strip()[:200]
    ticket.body = body
    author = request.session.get("user", "NOC")
    steps = [code for code, _label in TICKET_STEPS]
    if ticket.status in steps:
        index = steps.index(ticket.status)
        if action == "next" and index < len(steps) - 1:
            ticket.status = steps[index + 1]
            db.add(TicketEvent(ticket_id=ticket.id, author=author, action="流转", body=f"进入{STEP_LABELS[ticket.status]}"))
        elif action == "prev" and index > 0:
            ticket.status = steps[index - 1]
            db.add(TicketEvent(ticket_id=ticket.id, author=author, action="退回", body=f"回到{STEP_LABELS[ticket.status]}"))
    if action == "cancel" and ticket.status != "done":
        ticket.status = "cancelled"
        db.add(TicketEvent(ticket_id=ticket.id, author=author, action="取消", body=comment.strip() or "工单已取消"))
    if comment.strip() and action != "cancel":
        db.add(TicketEvent(ticket_id=ticket.id, author=author, action="备注", body=comment.strip()[:1000]))
    db.commit()
    return redirect(f"/tickets/{ticket.id}")


@app.get("/circuits", response_class=HTMLResponse)
def circuits(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Circuit).order_by(Circuit.bandwidth_mbps.desc())).all()
    links = db.scalars(select(VxlanLink).order_by(VxlanLink.vni)).all()
    return render(request, "circuits.html", rows=rows, links=links)


@app.get("/suppliers", response_class=HTMLResponse)
def suppliers(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        select(IpRecord.supplier, func.count(), func.sum(case((IpRecord.status == "allocated", 1), else_=0)))
        .where(IpRecord.supplier != "")
        .group_by(IpRecord.supplier)
        .order_by(func.count().desc())
        .limit(40)
    ).all()
    returns = db.scalars(select(SupplierReturn).limit(80)).all()
    return render(request, "suppliers.html", rows=rows, returns=returns)


def _parse_dt(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _notice_ctx(place, impact, reason, duration, start, end, type_code):
    start_text = start.strftime("%Y-%m-%d %H:%M") if start else ""
    end_text = end.strftime("%Y-%m-%d %H:%M") if end else ""
    utc_start = (start - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if start else ""
    utc_end = (end - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if end else ""
    action = "线路割接" if type_code == "cutover" else "维护"
    return {
        "place": place,
        "impact": impact.strip() or place,
        "reason": reason,
        "duration": duration or "30分钟",
        "start": start_text,
        "end": end_text,
        "utc_start": utc_start,
        "utc_end": utc_end,
        "action": action,
        "cause_by": "机房线路",
        "symptom": "短时中断",
    }
