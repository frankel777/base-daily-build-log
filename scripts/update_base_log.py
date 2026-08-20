#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
SNAPSHOT_SLOT = os.environ.get("SNAPSHOT_SLOT", "").strip().lower()

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "base-snapshots.jsonl"
README_FILE = ROOT / "README.md"

JST = ZoneInfo("Asia/Tokyo")
VALID_SLOTS = {"morning", "afternoon", "evening"}


def rpc(method, params=None):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or []
    }).encode()

    req = urllib.request.Request(
        RPC_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "base-daily-build-log/1.0"
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode())

    if "error" in result:
        raise RuntimeError(f"RPC error for {method}: {result['error']}")

    return result["result"]


def hex_int(value):
    return int(value, 16) if value else 0


def gwei(value):
    return round(hex_int(value) / 1_000_000_000, 6)


def load_rows():
    if not DATA_FILE.exists():
        return []

    rows = []
    for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_rows(rows):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def update_readme(rows):
    start = "<!-- DAILY_TABLE_START -->"
    end = "<!-- DAILY_TABLE_END -->"
    text = README_FILE.read_text(encoding="utf-8")

    latest = rows[-30:][::-1]

    lines = [
        "| Date (JST) | Slot | Block | Δ blocks | Tx | Gas (gwei) | Base fee (gwei) | Gas used |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for r in latest:
        lines.append(
            f"| {r['date_jst']} | {r['slot']} | {r['block_number']:,} | "
            f"{r['block_delta']:,} | {r['tx_count']:,} | "
            f"{r['gas_price_gwei']} | {r['base_fee_gwei']} | "
            f"{r['gas_used']:,} |"
        )

    replacement = "\n".join(lines) if latest else "No snapshots yet."

    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)

    README_FILE.write_text(
        before + start + "\n" + replacement + "\n" + end + after,
        encoding="utf-8",
    )


def main():
    if SNAPSHOT_SLOT not in VALID_SLOTS:
        raise RuntimeError(
            f"SNAPSHOT_SLOT must be one of {sorted(VALID_SLOTS)}; got {SNAPSHOT_SLOT!r}"
        )

    chain_id = hex_int(rpc("eth_chainId"))
    if chain_id != 8453:
        raise RuntimeError(f"Unexpected chain ID: {chain_id}; expected Base Mainnet 8453")

    now_utc = datetime.now(timezone.utc)
    now_jst = now_utc.astimezone(JST)
    date_jst = now_jst.date().isoformat()

    rows = load_rows()

    for row in rows:
        if row.get("date_jst") == date_jst and row.get("slot") == SNAPSHOT_SLOT:
            print(f"Snapshot already exists for {date_jst} / {SNAPSHOT_SLOT}; no changes.")
            return

    block_number = hex_int(rpc("eth_blockNumber"))
    gas_price_hex = rpc("eth_gasPrice")
    block = rpc("eth_getBlockByNumber", ["latest", False])

    previous_block = rows[-1]["block_number"] if rows else block_number

    block_timestamp = datetime.fromtimestamp(
        hex_int(block["timestamp"]),
        tz=timezone.utc
    )

    row = {
        "date_jst": date_jst,
        "slot": SNAPSHOT_SLOT,
        "captured_at_utc": now_utc.isoformat(timespec="seconds"),
        "block_timestamp_utc": block_timestamp.isoformat(timespec="seconds"),
        "chain_id": chain_id,
        "block_number": block_number,
        "block_delta": block_number - previous_block,
        "tx_count": len(block.get("transactions", [])),
        "gas_price_gwei": gwei(gas_price_hex),
        "base_fee_gwei": gwei(block.get("baseFeePerGas", "0x0")),
        "gas_used": hex_int(block.get("gasUsed", "0x0")),
        "gas_limit": hex_int(block.get("gasLimit", "0x0")),
    }

    rows.append(row)
    write_rows(rows)
    update_readme(rows)

    print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
