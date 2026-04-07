"""
Twilio provisioning helper.

Usage
─────
  just twilio-list
  just twilio-buy country=CH
  just twilio-set-webhook +41XXXXXXXXX
  just balance

Requires TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()


def get_client() -> Client:
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        sys.exit("ERROR: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
    return Client(sid, token)


def list_numbers(client: Client) -> None:
    numbers = client.incoming_phone_numbers.list()
    if not numbers:
        print("No phone numbers found in your Twilio account.")
        return
    for n in numbers:
        print(f"  {n.phone_number}  SID={n.sid}  webhook={n.voice_url}")


def buy_number(client: Client, country: str, webhook_url: str) -> None:
    available = client.available_phone_numbers(country).local.list(
        voice_enabled=True,
        limit=5,
    )
    if not available:
        sys.exit(f"No local voice-capable numbers available in country '{country}'")

    number = available[0].phone_number
    print(f"Purchasing {number} …")
    purchased = client.incoming_phone_numbers.create(
        phone_number=number,
        voice_url=webhook_url,
        voice_method="POST",
    )
    print(f"Done. Phone number: {purchased.phone_number}  SID: {purchased.sid}")
    print(f"\nAdd to your .env:\n  TWILIO_PHONE_NUMBER={purchased.phone_number}")


def show_balance(client: Client) -> None:
    balance = client.api.account.balance.fetch()
    print(f"Balance:        {balance.balance} {balance.currency}")

    records = client.usage.records.this_month.list(category="totalprice")
    if records:
        r = records[0]
        print(
            f"Month-to-date:  {r.price} {r.price_unit}  ({r.start_date} – {r.end_date})"
        )

    print(
        "\nSee details at"
        " https://console.twilio.com/us1/billing/manage-billing/billing-overview"
    )


def update_webhook(client: Client, phone_number: str, webhook_url: str) -> None:
    matches = client.incoming_phone_numbers.list(phone_number=phone_number)
    if not matches:
        sys.exit(f"Phone number {phone_number} not found in your account")
    record = matches[0]
    record.update(voice_url=webhook_url, voice_method="POST")
    print(f"Updated {phone_number} → webhook: {webhook_url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Twilio provisioning helper")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list-numbers", action="store_true", help="List existing numbers"
    )
    group.add_argument("--balance", action="store_true", help="Show account balance")
    group.add_argument("--buy", action="store_true", help="Buy a new phone number")
    group.add_argument(
        "--update-webhook",
        nargs=2,
        metavar=("PHONE", "URL"),
        help="Update voice webhook for an existing number",
    )

    parser.add_argument(
        "--country", default="CH", help="ISO country code for --buy (default: CH)"
    )
    parser.add_argument("--webhook", help="Webhook URL for --buy")

    args = parser.parse_args()
    client = get_client()

    if args.list_numbers:
        list_numbers(client)
    elif args.balance:
        show_balance(client)
    elif args.buy:
        if not args.webhook:
            sys.exit("--webhook URL is required with --buy")
        buy_number(client, args.country, args.webhook)
    elif args.update_webhook:
        phone, url = args.update_webhook
        update_webhook(client, phone, url)


if __name__ == "__main__":
    main()
