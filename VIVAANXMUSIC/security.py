import ipaddress
import os
import socket
from typing import Iterable
from urllib.parse import quote, quote_plus, urlsplit


class SecurityError(ValueError):
    pass


SENSITIVE_ENV_EXACT = {
    "API_HASH",
    "API_KEY",
    "BOT_TOKEN",
    "DATABASE_URL",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_API_KEYS",
    "DEEP_API",
    "GIT_TOKEN",
    "HEROKU_API_KEY",
    "MONGO_DB_URI",
    "SPOTIFY_CLIENT_SECRET",
    "STRING_SESSION",
    "STRING_SESSION2",
    "STRING_SESSION3",
    "STRING_SESSION4",
    "STRING_SESSION5",
    "WORKER_FALLBACK_API_KEY",
    "YT_API_KEY",
}
SENSITIVE_ENV_HINTS = ("TOKEN", "SECRET", "SESSION", "PASSWORD", "COOKIE", "MONGO")
SAFE_SUBPROCESS_ENV_KEYS = {
    "ALLUSERSPROFILE",
    "APPDATA",
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "LD_LIBRARY_PATH",
    "LIBRARY_PATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PYTHONHOME",
    "PYTHONIOENCODING",
    "PYTHONPATH",
    "PYTHONUTF8",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "VIRTUAL_ENV",
    "WINDIR",
    "DYLD_LIBRARY_PATH",
}
SECRET_CONFIG_ATTRS = (
    "API_HASH",
    "BOT_TOKEN",
    "MONGO_DB_URI",
    "API_KEY",
    "DEEP_API",
    "DASHSCOPE_API_KEY",
    "YT_API_KEY",
    "HEROKU_API_KEY",
    "GIT_TOKEN",
    "REPLICATE_API_TOKEN",
    "SPOTIFY_CLIENT_SECRET",
    "STRING1",
    "STRING2",
    "STRING3",
    "STRING4",
    "STRING5",
)
BLOCKED_HOSTS = {"localhost"}
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")


def _looks_sensitive_env_name(name: str) -> bool:
    upper_name = str(name or "").upper()
    return upper_name in SENSITIVE_ENV_EXACT or any(
        hint in upper_name for hint in SENSITIVE_ENV_HINTS
    )


def _clean_secret(value) -> str | None:
    if value is None:
        return None
    secret = str(value).strip()
    if len(secret) < 6:
        return None
    return secret


def _secret_variants(secret: str) -> set[str]:
    variants = {secret}
    quoted = quote(secret, safe="")
    quoted_plus = quote_plus(secret)
    if quoted:
        variants.add(quoted)
    if quoted_plus:
        variants.add(quoted_plus)
    return {item for item in variants if item}


def collect_secret_values(extra: Iterable[str] | None = None) -> list[str]:
    values: set[str] = set()
    for key, value in os.environ.items():
        if _looks_sensitive_env_name(key):
            cleaned = _clean_secret(value)
            if cleaned:
                values.add(cleaned)

    try:
        import config

        for attr in SECRET_CONFIG_ATTRS:
            cleaned = _clean_secret(getattr(config, attr, None))
            if cleaned:
                values.add(cleaned)
    except Exception:
        pass

    for value in extra or ():
        cleaned = _clean_secret(value)
        if cleaned:
            values.add(cleaned)

    expanded: set[str] = set()
    for secret in values:
        expanded.update(_secret_variants(secret))
    return sorted(expanded, key=len, reverse=True)


def redact_secrets(text):
    if not isinstance(text, str) or not text:
        return text

    redacted = text
    for secret in collect_secret_values():
        if secret in redacted:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def contains_secret_value(text: str | None) -> bool:
    if not text:
        return False
    return any(secret in text for secret in collect_secret_values())


def build_subprocess_env(extra_allowed: Iterable[str] | None = None) -> dict[str, str]:
    safe_env = {}
    allowed_keys = SAFE_SUBPROCESS_ENV_KEYS | set(extra_allowed or ())
    for key in allowed_keys:
        value = os.environ.get(key)
        if value:
            safe_env[key] = value
    safe_env.setdefault("PYTHONIOENCODING", "utf-8")
    safe_env.setdefault("PYTHONUTF8", "1")
    return safe_env


def drop_sensitive_env_vars(preserve: Iterable[str] | None = None) -> list[str]:
    preserved = {item.upper() for item in (preserve or ())}
    removed: list[str] = []
    for key in list(os.environ):
        if key.upper() in preserved:
            continue
        if _looks_sensitive_env_name(key):
            os.environ.pop(key, None)
            removed.append(key)
    return sorted(removed)


def _is_public_ip(ip_text: str) -> bool:
    ip_obj = ipaddress.ip_address(ip_text)
    return not any(
        (
            ip_obj.is_loopback,
            ip_obj.is_link_local,
            ip_obj.is_multicast,
            ip_obj.is_private,
            ip_obj.is_reserved,
            ip_obj.is_unspecified,
        )
    )


def _resolve_host_ips(hostname: str) -> set[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SecurityError(f"Could not resolve host: {hostname}") from exc

    resolved: set[str] = set()
    for family, _, _, _, sockaddr in infos:
        if family == socket.AF_INET:
            resolved.add(sockaddr[0])
        elif family == socket.AF_INET6:
            resolved.add(sockaddr[0])
    if not resolved:
        raise SecurityError(f"Could not resolve host: {hostname}")
    return resolved


def _host_matches(host: str, allowed_hosts: Iterable[str], allow_subdomains: bool) -> bool:
    normalized_host = host.lower().rstrip(".")
    normalized_allowed = {item.lower().rstrip(".") for item in allowed_hosts}
    if normalized_host in normalized_allowed:
        return True
    if allow_subdomains:
        return any(normalized_host.endswith(f".{allowed}") for allowed in normalized_allowed)
    return False


def validate_public_http_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    allow_subdomains: bool = False,
) -> str:
    candidate = (url or "").strip()
    if not candidate:
        raise SecurityError("URL is required.")
    if contains_secret_value(candidate):
        raise SecurityError("URL contains a protected secret value.")

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SecurityError("Only http:// or https:// URLs are allowed.")
    if not parsed.hostname:
        raise SecurityError("URL host is missing.")
    if parsed.username or parsed.password:
        raise SecurityError("Credentialed URLs are not allowed.")

    host = parsed.hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTS or any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES):
        raise SecurityError("Local or internal hosts are blocked.")
    if allowed_hosts and not _host_matches(host, allowed_hosts, allow_subdomains):
        raise SecurityError("This host is not allowed.")

    try:
        direct_ip = ipaddress.ip_address(host)
    except ValueError:
        resolved_ips = _resolve_host_ips(host)
        for resolved_ip in resolved_ips:
            if not _is_public_ip(resolved_ip):
                raise SecurityError("Private or local network targets are blocked.")
    else:
        if not _is_public_ip(str(direct_ip)):
            raise SecurityError("Private or local network targets are blocked.")

    return candidate


def validate_github_repo_url(url: str) -> str:
    safe_url = validate_public_http_url(url, allowed_hosts={"github.com", "www.github.com"})
    parsed = urlsplit(safe_url)
    if parsed.scheme.lower() != "https":
        raise SecurityError("Repository URL must use https://")
    if parsed.query or parsed.fragment:
        raise SecurityError("Repository URL must not contain query strings or fragments.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise SecurityError("Repository URL must be in the form https://github.com/<owner>/<repo>")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise SecurityError("Repository URL must include owner and repo.")

    return f"https://github.com/{owner}/{repo}.git"
