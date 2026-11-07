"""Strict probe contracts shared by the offline configurator and native installer.

No networking or persistence runs here. Runtime evidence stays on RouterOS.
"""
import ipaddress
import re

STRICT_FIELDS=('http_codes','http_path','http_expected_body','dns_expected_ips')
HTTP_TYPES={'http-get','https-get'}
MAX_BODY_BYTES=1024
MAX_STRICT_PROBES=16


def requires_fetch(probe):
    return 'http_expected_body' in probe or probe.get('http_path','/')!='/'


def native_type(probe):
    return 'tcp-conn' if requires_fetch(probe) else probe['type']


def http_codes(probe):
    return ','.join(str(n) for n in sorted(probe['http_codes'])) if 'http_codes' in probe else '200-299'


def validate_probe(probe):
    kind=probe['type']
    if any(field in probe for field in ('http_codes','http_path','http_expected_body')) and kind not in HTTP_TYPES:
        raise ValueError('HTTP expectations require an HTTP/HTTPS probe')
    if 'http_codes' in probe:
        codes=probe['http_codes']
        if not isinstance(codes,list) or not 1<=len(codes)<=16 or any(type(n) is not int or not 100<=n<=599 for n in codes) or len(set(codes))!=len(codes):
            raise ValueError('http_codes must contain 1..16 distinct HTTP status integers')
    if 'http_path' in probe:
        path=probe['http_path']
        if not isinstance(path,str) or not 1<=len(path)<=256 or not path.startswith('/') or path.startswith('//') or not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@/?%\-]*",path):
            raise ValueError('http_path must be a bounded origin-relative ASCII path/query')
        if re.search(r'%(?![0-9A-Fa-f]{2})',path) or re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f)',path,re.I):
            raise ValueError('http_path contains invalid escaping or control characters')
    if 'http_expected_body' in probe:
        body=probe['http_expected_body']
        if not isinstance(body,str) or len(body.encode('utf-8'))>MAX_BODY_BYTES or '\0' in body:
            raise ValueError('http_expected_body must be UTF-8 text up to 1024 bytes without NUL')
    if requires_fetch(probe) and any(not 200<=code<=299 for code in probe.get('http_codes',[])):
        raise ValueError('HTTP body/path checks require 2xx codes; use native Netwatch for non-2xx status expectations')
    if 'dns_expected_ips' in probe:
        values=probe['dns_expected_ips']
        if kind!='dns':raise ValueError('dns_expected_ips requires a DNS probe')
        if not isinstance(values,list) or not 1<=len(values)<=16 or any(not isinstance(ip,str) for ip in values) or len(set(values))!=len(values):
            raise ValueError('dns_expected_ips must contain 1..16 distinct IPv4 addresses')
        for ip in values:
            try:value=ipaddress.IPv4Address(ip)
            except ValueError:raise ValueError('Invalid expected DNS IPv4 address') from None
            if str(value)!=ip or value.is_multicast or value.is_unspecified or int(value)==0xffffffff:
                raise ValueError('Invalid expected DNS IPv4 address')
    return probe
