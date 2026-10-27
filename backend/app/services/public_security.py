"""Validate public exposure before database initialization or container services start."""
import ipaddress
import os
import re


def _valid_host(value: str) -> bool:
    if not value or value == "*":
        return False
    try:
        if "/" in value:
            network = ipaddress.ip_network(value, strict=False)
            return network.prefixlen > 0
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    hostname = value[2:] if value.startswith("*.") else value
    labels = hostname.rstrip(".").split(".")
    return (len(hostname.rstrip(".")) <= 253 and "*" not in hostname
            and (not value.startswith("*.") or len(labels) >= 2)
            and all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                    for label in labels))


def _valid_proxy(value: str) -> bool:
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    # An explicit finite network is an administrator's trust decision. Never
    # accept a catch-all; a single unspecified address is not a proxy endpoint.
    return (network.prefixlen > 0 and not network.network_address.is_multicast
            and not (network.num_addresses == 1 and network.network_address.is_unspecified))


def validate_public_settings(*, public_mode: bool, cookie_secure: bool,
                             force_https: bool, trusted_hosts: list[str],
                             forwarded_allow_ips: str) -> None:
    if not public_mode:
        return
    errors = []
    if not cookie_secure:
        errors.append("COOKIE_SECURE 必须为 1")
    if not force_https:
        errors.append("FORCE_HTTPS 必须为 1")
    if not trusted_hosts or not all(_valid_host(host) for host in trusted_hosts):
        errors.append("TRUSTED_HOSTS 必须列出合法域名/IP，不允许 *、空条目或全地址网段")
    proxies = [part.strip() for part in forwarded_allow_ips.split(",")]
    if not all(_valid_proxy(proxy) for proxy in proxies):
        errors.append("FORWARDED_ALLOW_IPS 必须明确列出合法代理 IP 或有限网段，不允许 *、全地址网段或空条目")
    if errors:
        raise RuntimeError("PUBLIC_MODE=1 公网安全配置不完整：" + "；".join(errors))


def validate_environment() -> None:
    validate_public_settings(
        public_mode=os.getenv("PUBLIC_MODE", "0") == "1",
        cookie_secure=os.getenv("COOKIE_SECURE", "0") == "1",
        force_https=os.getenv("FORCE_HTTPS", "0") == "1",
        trusted_hosts=[part.strip() for part in os.getenv("TRUSTED_HOSTS", "*").split(",")],
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", ""),
    )


if __name__ == "__main__":
    validate_environment()
