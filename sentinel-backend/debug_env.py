"""Diagnose why SARVAM_API_KEY is being read as empty."""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"

print("=" * 70)
print("SARVAM .ENV DEBUGGER")
print("=" * 70)

sys_key = os.environ.get("SARVAM_API_KEY")
print(f"\n[1] System env BEFORE load_dotenv:")
print(f"    Present: {sys_key is not None}")
print(f"    Value repr: {repr(sys_key)}")
print(f"    Length: {len(sys_key) if sys_key else 0}")

print(f"\n[2] File at {ENV_FILE}")
print(f"    Exists: {ENV_FILE.exists()}")
print(f"    Size: {ENV_FILE.stat().st_size} bytes")

with open(ENV_FILE, "rb") as f:
    first_bytes = f.read(4)
print(f"\n[3] First 4 bytes (hex): {first_bytes.hex().upper()}")
if first_bytes[:3] == b"\xef\xbb\xbf":
    print(f"    WARNING: UTF-8 BOM detected. This can break pydantic-settings.")

print(f"\n[4] Line-by-line content (with repr to expose hidden chars):")
with open(ENV_FILE, "r", encoding="utf-8-sig") as f:
    for i, line in enumerate(f.readlines(), 1):
        print(f"    Line {i}: {repr(line)}")

print(f"\n[5] Counting SARVAM_API_KEY occurrences:")
with open(ENV_FILE, "r", encoding="utf-8-sig") as f:
    content = f.read()
count = content.count("SARVAM_API_KEY=")
print(f"    Occurrences: {count}")
if count > 1:
    print(f"    WARNING: Multiple occurrences found. dotenv uses the LAST one.")

print(f"\n[6] Using python-dotenv directly:")
from dotenv import dotenv_values, load_dotenv

parsed = dotenv_values(ENV_FILE)
key = parsed.get("SARVAM_API_KEY")
print(f"    dotenv_values('SARVAM_API_KEY'): {repr(key)}")
print(f"    Length: {len(key) if key else 0}")

print(f"\n[7] Using pydantic-settings:")
from app.config import settings

print(f"    settings.SARVAM_API_KEY repr: {repr(settings.SARVAM_API_KEY)}")
print(f"    Length: {len(settings.SARVAM_API_KEY)}")
print(f"    First 4 chars: {settings.SARVAM_API_KEY[:4] if settings.SARVAM_API_KEY else 'EMPTY'}")

print(f"\n[8] System env AFTER load_dotenv:")
load_dotenv(ENV_FILE, override=True)
sys_key_after = os.environ.get("SARVAM_API_KEY")
print(f"    Length: {len(sys_key_after) if sys_key_after else 0}")

print("\n" + "=" * 70)
print("DIAGNOSIS")
print("=" * 70)

if not parsed.get("SARVAM_API_KEY"):
    print("ROOT CAUSE: The .env file does not contain a non-empty SARVAM_API_KEY value.")
    print("FIX: Edit .env. Make sure the line reads: SARVAM_API_KEY=<actual_key>")
    print("     (no space around equals, no quotes, the key value must be present)")
elif sys_key == "":
    print("ROOT CAUSE: System-level env var SARVAM_API_KEY is set to empty string.")
    print("            This overrides the .env file value.")
    print("FIX (PowerShell): [Environment]::SetEnvironmentVariable('SARVAM_API_KEY', $null, 'User')")
    print("                  Then close and reopen the terminal.")
elif first_bytes[:3] == b"\xef\xbb\xbf":
    print("ROOT CAUSE: UTF-8 BOM in .env file confuses pydantic-settings.")
    print("FIX: Re-save .env without BOM. Use Notepad++ or VS Code (UTF-8, not UTF-8 with BOM).")
elif content.count("SARVAM_API_KEY=") > 1:
    print("ROOT CAUSE: Multiple SARVAM_API_KEY lines, the last one might be empty.")
    print("FIX: Edit .env, keep only one SARVAM_API_KEY line.")
elif settings.SARVAM_API_KEY != parsed.get("SARVAM_API_KEY"):
    print("ROOT CAUSE: pydantic-settings is not reading the same value as python-dotenv.")
    print("FIX: Check app/config.py - env_file path, encoding, field name match.")
else:
    print("OK: SARVAM_API_KEY is non-empty and pydantic-settings matches python-dotenv.")
    print("If chat still fails, inspect the Sarvam call path or the configured SARVAM_MODEL.")
