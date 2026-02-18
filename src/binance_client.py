import hmac
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional
from urllib.parse import urlencode, quote

import requests


@dataclass
class BinanceClient:
    base_url: str
    api_key: str
    api_secret: str
    recv_window: int = 5000
    timeout: int = 10

    def _ts(self) -> int:
        return int(time.time() * 1000)

    def _encode(self, params: List[Tuple[str, Any]]) -> str:
        # Build the exact URL-encoded query string to be signed and sent
        return urlencode([(k, str(v)) for k, v in params], quote_via=quote, safe="")

    def _sign(self, query_string: str) -> str:
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = params or {}
        headers = {}

        if signed:
            if not self.api_key or not self.api_secret:
                raise ValueError("Missing API key/secret for signed request")
            headers["X-MBX-APIKEY"] = self.api_key

            items: List[Tuple[str, Any]] = list(params.items())
            items.append(("recvWindow", self.recv_window))
            items.append(("timestamp", self._ts()))
            qs = self._encode(items)
            sig = self._sign(qs)
            qs = f"{qs}&signature={sig}"
        else:
            qs = self._encode(list(params.items())) if params else ""

        url = f"{self.base_url}{path}"
        if qs:
            url = f"{url}?{qs}"

        r = requests.request(method, url, headers=headers, timeout=self.timeout)
        # Raise useful errors
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} failed {r.status_code}: {r.text}")
        return r.json() if r.text else {}

    # Convenience wrappers
    def get(
        self, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False
    ) -> Any:
        return self.request("GET", path, params=params, signed=signed)

    def post(
        self, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False
    ) -> Any:
        return self.request("POST", path, params=params, signed=signed)

    def delete(
        self, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False
    ) -> Any:
        return self.request("DELETE", path, params=params, signed=signed)
