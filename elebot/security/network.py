"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),   # 运营商级 NAT，默认按内网处理。
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地地址，也覆盖常见云元数据入口。
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),          # IPv6 本地唯一地址。
    ipaddress.ip_network("fe80::/10"),         # IPv6 链路本地地址。
]

_URL_RE = re.compile(r"https?://[^\s\"'`;|<>]+", re.IGNORECASE)

_allowed_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []


def configure_ssrf_whitelist(cidrs: list[str]) -> None:
    """配置允许放行的网段白名单。

    默认规则会拦掉所有私网和本地地址。
    如果部署环境必须访问特定内网段，可以在这里显式开口，而不是直接放松整体校验。
    """
    global _allowed_networks
    nets = []
    for cidr in cidrs:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            pass
    _allowed_networks = nets


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if _allowed_networks and any(addr in net for net in _allowed_networks):
        return False
    return any(addr in net for net in _BLOCKED_NETWORKS)


def validate_url_target(url: str) -> tuple[bool, str]:
    """校验某个 URL 是否适合发起外部请求。

    这里不仅检查协议是否合法，还会把域名解析成 IP 再逐个过一遍内网规则，
    避免攻击者用公开域名指向本地或私网地址绕过 SSRF 防护。
    """
    try:
        p = urlparse(url)
    except Exception as e:
        return False, str(e)

    if p.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
    if not p.netloc:
        return False, "Missing domain"

    hostname = p.hostname
    if not hostname:
        return False, "Missing hostname"

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_private(addr):
            return False, f"Blocked: {hostname} resolves to private/internal address {addr}"

    return True, ""


def validate_resolved_url(url: str) -> tuple[bool, str]:
    """校验已经得到的跳转目标是否仍然安全。

    这个入口主要用于处理重定向：
    首次请求前会校验原始 URL，跳转后再补一次校验，避免被带进内网地址。
    """
    try:
        p = urlparse(url)
    except Exception:
        return True, ""

    hostname = p.hostname
    if not hostname:
        return True, ""

    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private(addr):
            return False, f"Redirect target is a private address: {addr}"
    except ValueError:
        # 跳转目标不一定直接给 IP，因此域名场景仍要补一次解析校验。
        try:
            infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return True, ""
        for info in infos:
            try:
                addr = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _is_private(addr):
                return False, f"Redirect target {hostname} resolves to private address {addr}"

    return True, ""


def contains_internal_url(command: str) -> bool:
    """判断一段命令文本里是否夹带了指向内网的 URL。"""
    for m in _URL_RE.finditer(command):
        url = m.group(0)
        ok, _ = validate_url_target(url)
        if not ok:
            return True
    return False
