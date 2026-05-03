"""
Hindsight Plugin — User-Triggered Setup & Health Check

Run from the Plugins UI to install dependencies and verify connectivity.
Safe to run multiple times.
"""

import subprocess
import sys

_PACKAGE = "hindsight-client>=0.4.0"


def main():
    # --- Step 1: Install dependencies ---
    print("[1/3] Installing Hindsight SDK...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", _PACKAGE],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: pip install failed:\n{result.stderr}")
        return 1
    print(f"  ✓ {_PACKAGE} installed.")

    # --- Step 2: Verify import ---
    print("[2/3] Verifying Hindsight SDK import...")
    try:
        import hindsight_client  # noqa: F401
        version = getattr(hindsight_client, "__version__", "unknown")
        print(f"  ✓ hindsight_client SDK version: {version}")
    except ImportError as e:
        print(f"ERROR: Could not import hindsight_client: {e}")
        return 1

    # --- Step 3: Check configuration ---
    print("[3/3] Checking configuration...")
    import os
    
    base_url = os.environ.get("HINDSIGHT_BASE_URL", "").strip()
    if base_url:
        print(f"  ✓ HINDSIGHT_BASE_URL found: {base_url}")
    else:
        print("  ⚠ HINDSIGHT_BASE_URL not set.")
        print("    Set it as an environment variable before starting Agent Zero.")
        print("    Example: export HINDSIGHT_BASE_URL='http://localhost:8888'")

    api_key = os.environ.get("HINDSIGHT_API_KEY", "").strip()
    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        print(f"  ✓ HINDSIGHT_API_KEY found: {masked}")
    else:
        print("  ℹ HINDSIGHT_API_KEY not set (optional for local Hindsight servers).")

    # --- Step 4: Test connectivity ---
    if base_url:
        print("\n[Bonus] Testing connectivity...")
        try:
            from hindsight_client import Hindsight
            kwargs = {"base_url": base_url}
            if api_key:
                kwargs["api_key"] = api_key
            client = Hindsight(**kwargs)
            # Try a simple operation to verify connectivity
            print(f"  ✓ Hindsight client created for {base_url}")
        except Exception as e:
            print(f"  ⚠ Could not connect to Hindsight: {e}")

    print("\nDone. Plugin is ready to use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
