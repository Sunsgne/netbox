"""Pure helpers for the ZENLENET workbooks. No database access."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

SECRET_RE = re.compile(
    r"(?i)(password|passwd|密码\s*[:：=]|root/|ubuntu/|admin/|[a-z0-9._-]{2,}/[^\s]{6,})"
)
V4_RE = re.compile(
    r"(\d{1,3}(?:\.\d{1,3}){3})(?:\s*/\s*(\d{1,2}))?(?:\s*-\s*(\d{1,3}))?"
)
V6_RE = re.compile(r"([0-9a-fA-F:]{4,})/(\d{1,3})")

INFRA = {
    "网关",
    "gateway",
    "自用",
    "自用预留",
    "自用测试",
    "内部使用",
    "内部",
    "ros",
    "routeros",
    "routeos",
    "monitor",
    "ipmi",
    "server-ipmi",
    "隧道机",
    "供应商机器",
    "宿主机",
    "自用服务器",
    "自用-esxi",
    "自用-routeros",
}

SUPPLIERS = {
    "zenlayer",
    "bunny",
    "wisdom",
    "nuuk",
    "sizhan",
    "cnix",
    "ipxo",
    "flarespeed",
    "moack",
    "fpt",
    "tf",
    "tianfeng",
    "光速",
    "思栈",
    "云桥通",
    "奥飞",
    "朗桥",
    "郎桥",
    "zlidc",
}

ALIASES = {
    "lightwan": "LightWAN",
    "light wan": "LightWAN",
    "global": "Global IP Tech",
    "global ip tech": "Global IP Tech",
    "qingwang": "轻网",
    "轻网": "轻网",
    "ruiyou": "睿友",
    "ruike": "睿客",
    "ruike-cnix": "睿客",
    "super": "Super",
    "livecom": "Livecom",
    "livecom-爱讯达": "Livecom",
    "haitang": "海棠",
    "海棠": "海棠",
    "dianji": "典基",
    "典基": "典基",
    "chengyang": "晨阳",
    "chenyang": "晨阳",
    "sdwan": "SDWAN",
    "guoxin": "国新",
    "南捷": "南捷",
    "走起": "走起",
    "云森处": "云森处",
    "紫鸟": "紫鸟",
    "优咖": "优咖",
    "顺网": "顺网",
    "电科": "电科",
    "合讯": "合讯",
    "有孚香港": "有孚香港",
    "速宝": "速宝",
    "联云": "联云",
    "联云世纪": "联云",
    "奇葩游戏": "奇葩游戏",
    "蚂蚁": "蚂蚁",
    "集铁": "集铁",
    "超频王": "超频王",
    "goalnow network": "Goalnow",
    "itforce": "ITForce",
    "yunsenchu": "云森处",
}


def first_line(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ").replace("\xa0", " ").strip()
    if not text:
        return ""
    text = text.split("\n")[0].strip()
    return re.sub(r"\s+", " ", text)


def clean_remark(*parts) -> str:
    bits = []
    for part in parts:
        if part is None:
            continue
        text = str(part).replace("\u3000", " ").strip()
        if not text:
            continue
        if SECRET_RE.search(text):
            continue
        bits.append(re.sub(r"\s+", " ", text))
    return " | ".join(bits)[:300]


def valid_v4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(item) <= 255 for item in parts)
    except ValueError:
        return False


def is_private_v4(ip: str) -> bool:
    a, b, _, _ = (int(part) for part in ip.split("."))
    if a == 10 or (a == 192 and b == 168):
        return True
    return a == 172 and 16 <= b <= 31


def extract_ips(text) -> list[tuple[str, int]]:
    if text is None:
        return []
    raw = str(text).replace("（", " ").replace("）", " ")
    found = []
    seen = set()
    for match in V4_RE.finditer(raw):
        ip, prefix, end = match.group(1), match.group(2), match.group(3)
        if not valid_v4(ip):
            continue
        if prefix:
            plen = int(prefix)
            if not 0 < plen <= 32:
                continue
            key = (ip, plen)
            if key not in seen:
                seen.add(key)
                found.append(key)
            continue
        if end is not None:
            start = int(ip.split(".")[-1])
            last = int(end)
            if start <= last <= 255 and last - start <= 32:
                base = ip.rsplit(".", 1)[0]
                for host in range(start, last + 1):
                    addr = f"{base}.{host}"
                    if (addr, 32) not in seen:
                        seen.add((addr, 32))
                        found.append((addr, 32))
                continue
        if (ip, 32) not in seen:
            seen.add((ip, 32))
            found.append((ip, 32))
    return found


def extract_v6(text) -> list[tuple[str, int]]:
    if text is None:
        return []
    found = []
    seen = set()
    for match in V6_RE.finditer(str(text)):
        addr, plen_s = match.group(1), int(match.group(2))
        if "::" not in addr and addr.count(":") < 2:
            continue
        if not 0 < plen_s <= 128:
            continue
        key = (addr.lower(), plen_s)
        if key not in seen:
            seen.add(key)
            found.append(key)
    return found


def parse_dates(text) -> list[date]:
    if not text:
        return []
    found = []
    for match in re.finditer(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", str(text)):
        found.append(_safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
    for match in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})", str(text)):
        found.append(_safe_date(int(match.group(3)), int(match.group(1)), int(match.group(2))))
    return [item for item in found if item]


def parse_expiry(text):
    dates = parse_dates(text)
    return dates[-1] if dates else None


def _safe_date(year: int, month: int, day: int):
    if year < 2020 or year > 2035:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_bandwidth(text):
    if text is None:
        return None
    raw = str(text).strip()
    if not raw or raw == "\u3000":
        return None
    if "95" in raw:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([GgMm])", raw)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2).lower() == "g":
        value *= 1000
    if value < 1:
        return None
    return int(value)


def role_from_header(header: str) -> str:
    text = header or ""
    upper = text.upper()
    if "家庭" in text:
        return "home"
    if "原生" in text:
        return "native"
    if "BGP" in upper:
        return "bgp"
    if "IDC" in upper:
        return "idc"
    if "LOCAL" in upper or "本地" in text:
        return "local"
    return "other"


def dc_type_for(supplier: str) -> str:
    text = (supplier or "").lower()
    if any(token in text for token in ("aws", "gcp", "azure", "公有云")):
        return "公有云"
    if "zenlenet" in text:
        return "主营机房"
    if not text:
        return "POP点"
    return "第三方"


def classify_customer(raw):
    """Return kind: customer, infra, empty, skip."""
    text = first_line(raw)
    if not text:
        return "empty", None
    text = re.sub(r"（[^）]{6,}）", "", text).strip()
    if not text:
        return "empty", None
    if SECRET_RE.search(text):
        return "skip", None
    if re.match(r"\d{4}[./-]\d", text) or any(token in text for token in ("回收", "剩", "测试组网")):
        return "skip", None
    if text.endswith("测试") and text not in {"测试", "自用测试"}:
        base = re.sub(r"(?i)\s*vm$", "", text[:-2].strip(" -/")).strip()
        kind, name = classify_customer(base)
        if kind == "customer":
            return "customer", name
    if any(token in text.lower() for token in ("routeos", "routeros", "隧道机", "交换机", "转发机器", "虚拟机")):
        return "infra", text
    if re.match(r"(?i)^(cs|cr|svr|ser|mgt|server)-", text) or re.match(r"^[A-Za-z]{2,4}\d-\d{2}-", text):
        return "infra", text
    if text.endswith("预留") and text not in {"预留", "自用预留"}:
        kind, name = classify_customer(text[:-2].strip())
        if kind == "customer":
            return "hold", name
    low = text.lower()
    if low in INFRA or text.startswith("自用") or "routeros" in low or low in {"ros", "ipmi", "monitor"}:
        return "infra", text
    if re.match(r"(?i)^(cs|cr|svr|mgt|server)[-.]", text):
        return "infra", text
    if any(token in text for token in ("代播", "到期", "网关", "上游", "广播", "预留")):
        return "skip", None
    if re.search(r"\d+\.\d+\.\d+\.\d+", text):
        return "skip", None
    if len(text) < 2 or len(text) > 40:
        return "skip", None
    if low in SUPPLIERS:
        return "skip", None
    return "customer", ALIASES.get(low, text)


def decide_status(kind: str, raw_label: str, remark: str, rgb: str, today: date | None = None):
    today = today or date.today()
    blob = f"{raw_label or ''} {remark or ''}"
    expiry = parse_expiry(blob)
    past_return = bool(expiry and expiry < today and ("退" in blob or "到期" in blob))
    if kind == "customer":
        if past_return:
            return "returning", expiry
        if "测试" in (raw_label or ""):
            return "testing", expiry
        return "allocated", expiry
    if kind == "infra":
        if "预留" in blob:
            return "reserved", expiry
        if "测试" in blob:
            return "testing", expiry
        return "internal", expiry
    if "预留" in blob:
        return "reserved", expiry
    if rgb == "FFFF00" or "测试" in blob:
        return "testing", expiry
    if rgb == "92D050":
        return "free", expiry
    if rgb == "FFC000":
        return "allocated", expiry
    if past_return:
        return "returning", expiry
    return "free", expiry


def product_of(type_text: str, default: str) -> str:
    text = (type_text or "").upper()
    if "SDWAN" in text or "SD-WAN" in text:
        return "SDWAN"
    if "RMIPT" in text:
        return "RMIPT"
    if "PL" in text:
        return "PL"
    if "VM" in text:
        return "VM"
    if re.search(r"\bIPT\b", text):
        return "IPT"
    return default


def render_notice(template: str, ctx: dict) -> str:
    replacements = [
        ("【受影响IP/IP段/专线名称/节点名称】", ctx.get("impact") or ""),
        ("【受影响专线/节点/IP段/业务名称】", ctx.get("impact") or ""),
        ("【例如：SDWAN线路 / 接入点服务器 / 指定业务节点】", ctx.get("impact") or ""),
        ("【涉及IP】", ctx.get("impact") or ""),
        ("【受影响范围】", ctx.get("impact") or ""),
        ("【维护地区/节点】", ctx.get("place") or ""),
        ("【地区/节点】", ctx.get("place") or ""),
        ("【维护地区】", ctx.get("place") or ""),
        ("【UTC开始时间】", ctx.get("utc_start") or ""),
        ("【UTC结束时间】", ctx.get("utc_end") or ""),
        ("【开始时间】", ctx.get("start") or ""),
        ("【结束时间】", ctx.get("end") or ""),
        ("【割接原因】", ctx.get("reason") or ""),
        ("【X分钟/X小时】", ctx.get("duration") or ""),
        ("【配置升级/优化调整/割接】", ctx.get("action") or "维护"),
        ("【线路割接/设备迁移/机房迁移】", ctx.get("action") or "线路割接"),
        ("【网络扩容/线路优化/紧急维护】", ctx.get("action") or "紧急维护"),
        ("【机房/运营商/线路】", ctx.get("cause_by") or "线路"),
        ("【短时中断/访问波动/时延升高/丢包】", ctx.get("symptom") or "短时中断"),
    ]
    text = template
    for src, dst in replacements:
        if dst:
            text = text.replace(src, dst)
    return text


def beijing_utc_pair(start: datetime, end: datetime):
    return (
        start.strftime("%Y-%m-%d %H:%M"),
        end.strftime("%Y-%m-%d %H:%M"),
        (start - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
        (end - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
    )
