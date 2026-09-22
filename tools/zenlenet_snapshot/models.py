"""Operational models.

IP inventory follows the NetBox IPAM objects that matter here (prefix, address,
site, tenant). Customers, orders, and invoices follow the Odoo partner / sales
order / customer invoice shape. Maintenance tickets follow a Jira-style board.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zenlenet_snapshot.db import Base


def now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="external")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    orders: Mapped[list["ServiceOrder"]] = relationship(back_populates="customer")
    addresses: Mapped[list["IpRecord"]] = relationship(back_populates="customer")


class IpRecord(Base):
    __tablename__ = "ip_records"
    __table_args__ = (UniqueConstraint("version", "address", "prefixlen", name="uq_ip"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=4, index=True)
    address: Mapped[str] = mapped_column(String(80), index=True)
    prefixlen: Mapped[int] = mapped_column(Integer, default=32)
    pop: Mapped[str] = mapped_column(String(80), default="", index=True)
    supplier: Mapped[str] = mapped_column(String(80), default="", index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="other")
    net_attr: Mapped[str] = mapped_column(String(20), default="公网", index=True)
    dc_type: Mapped[str] = mapped_column(String(20), default="第三方")
    status: Mapped[str] = mapped_column(String(20), default="free", index=True)
    usage: Mapped[str] = mapped_column(String(40), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(80), default="")
    customer: Mapped[Customer | None] = relationship(back_populates="addresses")

    @property
    def display(self) -> str:
        if self.version == 6 or self.prefixlen not in (32, 128):
            return f"{self.address}/{self.prefixlen}"
        return self.address


class ServiceOrder(Base):
    __tablename__ = "service_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    product: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    country: Mapped[str] = mapped_column(String(80), default="")
    pop_code: Mapped[str] = mapped_column(String(80), default="", index=True)
    bandwidth_text: Mapped[str] = mapped_column(String(80), default="")
    bw_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_text: Mapped[str] = mapped_column(Text, default="")
    supplier_name: Mapped[str] = mapped_column(String(80), default="")
    circuit_no: Mapped[str] = mapped_column(String(80), default="")
    vlan: Mapped[str] = mapped_column(String(40), default="")
    device: Mapped[str] = mapped_column(String(160), default="")
    spec: Mapped[str] = mapped_column(String(80), default="")
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    customer: Mapped[Customer] = relationship(back_populates="orders")


class Circuit(Base):
    __tablename__ = "circuits"
    id: Mapped[int] = mapped_column(primary_key=True)
    circuit_no: Mapped[str] = mapped_column(String(80), default="")
    a_city: Mapped[str] = mapped_column(String(40), default="")
    z_city: Mapped[str] = mapped_column(String(40), default="")
    a_vlan: Mapped[str] = mapped_column(String(40), default="")
    z_vlan: Mapped[str] = mapped_column(String(40), default="")
    bandwidth_mbps: Mapped[float] = mapped_column(Float, default=0)
    peak_mbps: Mapped[float] = mapped_column(Float, default=0)


class VxlanLink(Base):
    __tablename__ = "vxlan_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    vni: Mapped[str] = mapped_column(String(20), default="")
    a_end: Mapped[str] = mapped_column(String(160), default="")
    z_end: Mapped[str] = mapped_column(String(160), default="")
    customer_name: Mapped[str] = mapped_column(String(80), default="")
    vlan: Mapped[str] = mapped_column(String(40), default="")
    bandwidth: Mapped[str] = mapped_column(String(40), default="")
    purpose: Mapped[str] = mapped_column(String(80), default="")
    stopped: Mapped[str] = mapped_column(String(40), default="")


class SupplierReturn(Base):
    __tablename__ = "supplier_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier: Mapped[str] = mapped_column(String(80), default="")
    resource: Mapped[str] = mapped_column(String(160), default="")
    when_text: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class Price(Base):
    __tablename__ = "prices"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Float, default=0)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("customer_id", "period", name="uq_invoice_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    total: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    description: Mapped[str] = mapped_column(String(240))
    qty: Mapped[float] = mapped_column(Float, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    amount: Mapped[float] = mapped_column(Float, default=0)
    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class NoticeTemplate(Base):
    __tablename__ = "notice_templates"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    scene: Mapped[str] = mapped_column(String(120), default="")
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(20), unique=True)
    type_code: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(200))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    pop: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    impact: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(String(120), default="")
    duration: Mapped[str] = mapped_column(String(40), default="")
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    assignee: Mapped[str] = mapped_column(String(40), default="NOC")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    customer: Mapped[Customer | None] = relationship()
    events: Mapped[list["TicketEvent"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    author: Mapped[str] = mapped_column(String(40), default="NOC")
    action: Mapped[str] = mapped_column(String(40), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    ticket: Mapped[Ticket] = relationship(back_populates="events")
