#!/usr/bin/env python3

import argparse
import sys
import textwrap
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth


SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"


def soap_headers(action: str) -> dict:
    return {
        "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
    }


def soap_envelope(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tev="http://www.onvif.org/ver10/events/wsdl">'
        f"<s:Body>{body}</s:Body>"
        "</s:Envelope>"
    )


def parse_address(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    for elem in root.iter():
        if elem.tag.endswith("Address") and elem.text:
            return elem.text
    raise RuntimeError("SubscriptionReference.Address not found in SOAP response")


def print_response(label: str, response: requests.Response, limit: int = 2500) -> None:
    print(f"=== {label} ===")
    print(f"HTTP {response.status_code}")
    body = response.text[:limit]
    print(body)
    if len(response.text) > limit:
        print("... [truncated]")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an ONVIF pull-point subscription and try to poll it."
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--termination", default="PT5M")
    parser.add_argument("--timeout", default="PT5S")
    parser.add_argument("--message-limit", type=int, default=5)
    args = parser.parse_args()

    auth = HTTPDigestAuth(args.username, args.password)
    base_url = f"http://{args.host}:{args.port}/onvif/events_service"

    create_body = soap_envelope(
        f"<tev:CreatePullPointSubscription>"
        f"<tev:InitialTerminationTime>{args.termination}</tev:InitialTerminationTime>"
        f"</tev:CreatePullPointSubscription>"
    )
    create_resp = requests.post(
        base_url,
        data=create_body,
        headers=soap_headers(
            "http://www.onvif.org/ver10/events/wsdl/EventPortType/CreatePullPointSubscriptionRequest"
        ),
        auth=auth,
        timeout=15,
    )
    print_response("CreatePullPointSubscription", create_resp)
    create_resp.raise_for_status()

    subscription_url = parse_address(create_resp.text)
    print(f"Subscription URL: {subscription_url}\n")

    sync_body = soap_envelope("<tev:SetSynchronizationPoint/>")
    sync_resp = requests.post(
        subscription_url,
        data=sync_body,
        headers=soap_headers(
            "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/SetSynchronizationPointRequest"
        ),
        auth=auth,
        timeout=15,
    )
    print_response("SetSynchronizationPoint", sync_resp)

    pull_body = soap_envelope(
        f"<tev:PullMessages>"
        f"<tev:Timeout>{args.timeout}</tev:Timeout>"
        f"<tev:MessageLimit>{args.message_limit}</tev:MessageLimit>"
        f"</tev:PullMessages>"
    )
    pull_resp = requests.post(
        subscription_url,
        data=pull_body,
        headers=soap_headers(
            "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
        ),
        auth=auth,
        timeout=20,
    )
    print_response("PullMessages", pull_resp, limit=5000)

    if pull_resp.ok:
        return 0

    print(
        textwrap.dedent(
            """\
            Pull failed. The current device behavior seen in testing is:
            - CreatePullPointSubscription succeeds
            - PullMessages returns a SOAP fault with `NoSubscribe`
            This suggests the device advertises pull-point support but is rejecting the
            subscription when the poll request is made.
            """
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
