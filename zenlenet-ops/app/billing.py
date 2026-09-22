"""Demo invoices from in-service orders and unattached IP allocations."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from app.db import price_map
from app.models import Customer, Invoice, InvoiceLine, IpRecord, ServiceOrder


def order_lines(orders: list[ServiceOrder], prices: dict[str, float]) -> list[dict]:
    lines = []
    vm_groups: dict[str, list[ServiceOrder]] = defaultdict(list)
    for order in orders:
        if order.status != "active":
            continue
        if order.product == "VM":
            vm_groups[order.pop_code or order.country or "未标注"].append(order)
            continue
        amount, qty, unit, desc = _price_order(order, prices)
        if amount <= 0:
            continue
        lines.append({"description": desc, "qty": qty, "unit_price": unit, "amount": amount})
    unit = prices.get("vm", 0)
    for pop, items in sorted(vm_groups.items()):
        amount = round(unit * len(items), 2)
        if amount <= 0:
            continue
        lines.append(
            {
                "description": f"{pop} 云主机",
                "qty": len(items),
                "unit_price": unit,
                "amount": amount,
            }
        )
    return lines


def _price_order(order: ServiceOrder, prices: dict[str, float]):
    if order.product in {"IPT", "RMIPT"} and order.bw_mbps:
        unit = prices.get("ipt_mbps", 0)
        return round(order.bw_mbps * unit, 2), order.bw_mbps, unit, f"{order.pop_code or order.country} {order.product} {order.bandwidth_text}"
    if order.product in {"PL", "SDWAN"} and order.bw_mbps:
        unit = prices.get("pl_mbps", 0)
        label = "专线" if order.product == "PL" else "SD-WAN"
        where = order.pop_code or order.country or order.circuit_no
        return round(order.bw_mbps * unit, 2), order.bw_mbps, unit, f"{where} {label} {order.bandwidth_text}"
    if order.product == "托管":
        unit = prices.get("colo", 0)
        return unit, 1, unit, f"{order.pop_code} 托管 {order.spec}"
    return 0, 0, 0, ""


def unattached_ip_lines(session, customer_id: int, prices: dict[str, float]) -> list[dict]:
    """Bill allocated addresses only when the customer has no active order mentioning IP."""
    orders = session.scalars(
        select(ServiceOrder).where(ServiceOrder.customer_id == customer_id, ServiceOrder.status == "active")
    ).all()
    if any(order.ip_text for order in orders):
        return []
    v4 = session.scalars(
        select(IpRecord).where(
            IpRecord.customer_id == customer_id,
            IpRecord.version == 4,
            IpRecord.status == "allocated",
            IpRecord.prefixlen == 32,
        )
    ).all()
    v6 = session.scalars(
        select(IpRecord).where(
            IpRecord.customer_id == customer_id,
            IpRecord.version == 6,
            IpRecord.status == "allocated",
        )
    ).all()
    lines = []
    if v4:
        unit = prices.get("ipv4", 0)
        lines.append(
            {
                "description": "已分配 IPv4（未挂在网订单）",
                "qty": len(v4),
                "unit_price": unit,
                "amount": round(len(v4) * unit, 2),
            }
        )
    if v6:
        unit = prices.get("ipv6", 0)
        lines.append(
            {
                "description": "已分配 IPv6 前缀（未挂在网订单）",
                "qty": len(v6),
                "unit_price": unit,
                "amount": round(len(v6) * unit, 2),
            }
        )
    return [line for line in lines if line["amount"] > 0]


def generate_invoices(session, period: str, customer_id: int | None = None) -> int:
    prices = price_map(session)
    query = select(Customer).order_by(Customer.name)
    if customer_id:
        query = query.where(Customer.id == customer_id)
    created = 0
    existing_numbers = {row.number for row in session.scalars(select(Invoice.number))}
    sequence = len(existing_numbers) + 1
    for customer in session.scalars(query):
        if session.scalar(select(Invoice).where(Invoice.customer_id == customer.id, Invoice.period == period)):
            continue
        orders = session.scalars(select(ServiceOrder).where(ServiceOrder.customer_id == customer.id)).all()
        lines = order_lines(orders, prices) + unattached_ip_lines(session, customer.id, prices)
        if not lines:
            continue
        number = f"ZL-INV-{period.replace('-', '')}-{sequence:04d}"
        while number in existing_numbers:
            sequence += 1
            number = f"ZL-INV-{period.replace('-', '')}-{sequence:04d}"
        invoice = Invoice(
            number=number,
            customer_id=customer.id,
            period=period,
            status="draft",
            total=round(sum(line["amount"] for line in lines), 2),
        )
        session.add(invoice)
        session.flush()
        for line in lines:
            session.add(InvoiceLine(invoice_id=invoice.id, **line))
        existing_numbers.add(number)
        sequence += 1
        created += 1
    return created
