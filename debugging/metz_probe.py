#!/usr/bin/env python3
"""Read-only SOAP probe for Metz Classic RCRService. Python 3, no dependencies."""

import argparse
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SERVICE = "urn:metz.de:service:RCRService:1"
CONTROL_PATH = "/services/rcr/control/RCRService"
ACTIONS = ("GetOperationMode", "GetDeviceList", "GetPowerState", "GetActiveDevice")
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"


def soap_request(ip, action, timeout):
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{SERVICE}"/></s:Body>'
        '</s:Envelope>'
    ).encode("utf-8")
    url = f"http://{ip}:49200{CONTROL_PATH}"
    request = urllib.request.Request(
        url,
        data=envelope,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{SERVICE}#{action}"',
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def pretty_print(body):
    try:
        root = ET.fromstring(body)
        soap_body = root.find(f"{{{SOAP_NS}}}Body")
        if soap_body is None:
            print(body)
            return
        for element in soap_body:
            # No request arguments in these four read-only calls.
            for child in element:
                key = child.tag.rsplit("}", 1)[-1]
                value = (child.text or "").strip()
                print(f"  {key}: {value}")
            if not list(element):
                print("  ", ET.tostring(element, encoding="unicode"))
    except ET.ParseError:
        print(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", default="192.168.1.131", help="TV IPv4 address")
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout seconds")
    args = parser.parse_args()
    errors = 0
    for action in ACTIONS:
        print(f"\n=== {action} ===", flush=True)
        try:
            status, body = soap_request(args.ip, action, args.timeout)
            print(f"HTTP {status}")
            pretty_print(body)
            if status != 200:
                errors += 1
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"Request failed: {exc}")
            errors += 1
    return int(errors > 0)


if __name__ == "__main__":
    sys.exit(main())
