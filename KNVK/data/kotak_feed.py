# data/kotak_feed.py — Kotak Neo v2 SDK integration

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
from neo_api_client import NeoAPI

load_dotenv()


class KotakClient:

    def __init__(self):
        self.consumer_key  = os.getenv("KOTAK_CONSUMER_KEY")
        self.mobile        = os.getenv("KOTAK_MOBILE")
        self.ucc           = os.getenv("KOTAK_UCC")
        self.mpin          = os.getenv("KOTAK_MPIN")
        self.client        = None
        self.authenticated = False

    def is_authenticated(self) -> bool:
        return self.authenticated

    def login(self, totp: str) -> bool:
        try:
            self.client = NeoAPI(
                consumer_key = self.consumer_key,
                environment  = "prod",
                access_token = None,
                neo_fin_key  = None
            )
            print("Step 1 — TOTP login...")
            resp1 = self.client.totp_login(
                mobile_number = self.mobile,
                ucc           = self.ucc,
                totp          = totp
            )
            print(f"Step 1 response: {resp1}")
            if resp1.get("error"):
                print(f"TOTP login failed: {resp1['error']}")
                self.authenticated = False
                return False

            print("Step 2 — MPIN validation...")
            resp2 = self.client.totp_validate(mpin=self.mpin)
            print(f"Step 2 response: {resp2}")
            if resp2.get("error"):
                print(f"MPIN validation failed: {resp2['error']}")
                self.authenticated = False
                return False

            self.authenticated = True
            print("\nAuthentication successful!")
            return True

        except Exception as e:
            print(f"Login error: {e}")
            self.authenticated = False
            return False

    def get_quote(self, instrument_tokens: list) -> dict:
        if not self.authenticated:
            return {}
        try:
            return self.client.quotes(
                instrument_tokens = instrument_tokens,
                quote_type        = "ltp"
            )
        except Exception as e:
            return {}

    def get_ohlc_today(self, token: str) -> dict:
        if not self.authenticated:
            return {}
        try:
            # try OHLC first for intraday high/low
            ohlc_result = self.client.quotes(
                instrument_tokens = [{
                    "instrument_token": token,
                    "exchange_segment": "nse_cm"
                }],
                quote_type = "ohlc"
            )

            # get LTP separately — more reliable
            ltp_result = self.client.quotes(
                instrument_tokens = [{
                    "instrument_token": token,
                    "exchange_segment": "nse_cm"
                }],
                quote_type = "ltp"
            )

            ltp = 0.0
            if ltp_result and len(ltp_result) > 0:
                ltp = float(ltp_result[0].get("ltp", 0))

            ohlc = {}
            if ohlc_result and len(ohlc_result) > 0:
                ohlc = ohlc_result[0].get("ohlc", {})

            # if we have LTP use it — most reliable
            if ltp > 0:
                return {
                    "high":  float(ohlc.get("high", ltp)),
                    "low":   float(ohlc.get("low",  ltp)),
                    "close": ltp
                }

            return {}

        except Exception:
            # fallback — try plain LTP quote
            try:
                result = self.client.quotes(
                    instrument_tokens = [{
                        "instrument_token": token,
                        "exchange_segment": "nse_cm"
                    }],
                    quote_type = "ltp"
                )
                if result and len(result) > 0:
                    ltp = float(result[0].get("ltp", 0))
                    if ltp > 0:
                        return {"high": ltp, "low": ltp, "close": ltp}
            except:
                pass
            return {}   

    def get_positions(self) -> dict:
        if not self.authenticated:
            return {}
        try:
            return self.client.positions()
        except Exception as e:
            return {}

    def get_limits(self) -> dict:
        if not self.authenticated:
            return {}
        try:
            return self.client.limits()
        except Exception as e:
            return {}

    def build_symbol_token_map(self, symbols: list) -> dict:
        token_map = {}
        for sym in symbols:
            try:
                results = self.client.search_scrip(
                    exchange_segment = "nse_cm",
                    symbol           = sym
                )
                if not results:
                    continue
                eq_result = next(
                    (r for r in results if r.get("pGroup") == "EQ"),
                    None
                )
                if eq_result:
                    token_map[sym] = str(eq_result["pSymbol"])
                    print(f"  {sym:<15} ✓ {eq_result['pSymbol']}")
                else:
                    print(f"  {sym:<15} ✗ no EQ group")
            except Exception as e:
                print(f"  {sym:<15} ✗ error: {e}")
        return token_map


if __name__ == "__main__":
    client = KotakClient()
    totp = input("Enter TOTP (you have 30 seconds): ")
    success = client.login(totp)
    if success:
        print("\nTesting BHEL OHLC...")
        from config import KOTAK_TOKEN_MAP
        ohlc = client.get_ohlc_today(KOTAK_TOKEN_MAP["BHEL"])
        print(f"BHEL: {ohlc}")
    else:
        print("Authentication failed.")