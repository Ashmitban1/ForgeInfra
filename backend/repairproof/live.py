"""Bounded Solana JSON-RPC and lazy, allowlisted local signing.

Import, configuration, and capabilities never contact RPC or load a keypair.
There is no key generation, funding, arbitrary signing API, or request retry.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat
import time
from urllib.parse import urlsplit
import uuid

import httpx

from backend.repairproof.memo import DEVNET_GENESIS, MemoAdapter, MemoConfig, ProviderError

METHODS = frozenset({"getGenesisHash", "getLatestBlockhash", "getFeeForMessage", "getBalance",
                     "getBlockHeight", "sendTransaction", "getSignatureStatuses", "getTransaction"})
MAX_RESPONSE_BYTES = 256_000


class LiveConfigurationError(ValueError):
    """Only safe configuration codes, never values/URLs/paths or secret data."""


def validate_endpoint(value):
    try:
        if not isinstance(value, str) or any(char.isspace() for char in value):
            raise ValueError()
        parsed = urlsplit(value)
        parsed.port  # Reject malformed ports before constructing an HTTP client.
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or "mainnet" in parsed.hostname.lower()):
            raise ValueError()
    except (ValueError, TypeError):
        raise LiveConfigurationError("invalid_solana_rpc_url") from None
    return value


@dataclass(frozen=True)
class LiveConfig:
    publisher: str
    keypair_path: str = field(repr=False)
    rpc_url: str = field(default="https://api.devnet.solana.com", repr=False)
    verify_rpc_url: str = field(default="https://api.devnet.solana.com", repr=False)
    max_fee_lamports: int = 10_000
    timeout_seconds: float = 10

    @classmethod
    def from_environment(cls):
        from solders.pubkey import Pubkey
        try:
            publisher = os.environ.get("SOLANA_ALLOWED_PUBLISHER", "").strip()
            key = Pubkey.from_string(publisher)
            if key == Pubkey.default() or not key.is_on_curve():
                raise ValueError()
            path = os.environ.get("SOLANA_PUBLISHER_KEYPAIR_PATH", "").strip()
            if (not path or not Path(path).is_absolute()
                    or Path(path).resolve().is_relative_to(Path(__file__).resolve().parents[2])):
                raise ValueError()
            genesis = os.environ.get("SOLANA_EXPECTED_GENESIS_HASH", DEVNET_GENESIS).strip()
            if genesis != DEVNET_GENESIS:
                raise ValueError()
            maximum = int(os.environ.get("SOLANA_MAX_FEE_LAMPORTS", "10000"))
            timeout = float(os.environ.get("SOLANA_RPC_TIMEOUT_SECONDS", "10"))
            if not 1 <= maximum <= 100_000 or not 1 <= timeout <= 30:
                raise ValueError()
            rpc = validate_endpoint(os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com").strip())
            verify_rpc = validate_endpoint(os.environ.get("SOLANA_VERIFY_RPC_URL", rpc).strip())
            return cls(publisher, path, rpc, verify_rpc, maximum, timeout)
        except (ValueError, TypeError):
            raise LiveConfigurationError("solana_publisher_configuration_required") from None


class JsonRpcClient:
    def __init__(self, url, timeout_seconds=10, *, transport=None):
        self._url = validate_endpoint(url)
        if not 1 <= timeout_seconds <= 30:
            raise LiveConfigurationError("invalid_solana_rpc_timeout")
        self._timeout = timeout_seconds
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=min(5, timeout_seconds)),
            transport=transport or httpx.HTTPTransport(retries=0), follow_redirects=False, trust_env=False,
            headers={"Accept-Encoding": "identity"})

    def call(self, method, params):
        if method not in METHODS or not isinstance(params, list):
            raise ProviderError("rpc_method_not_allowed")
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        try:
            with self._client.stream("POST", self._url, json={"jsonrpc": "2.0", "id": request_id,
                                                             "method": method, "params": params}) as response:
                if response.status_code != 200:
                    raise ProviderError("rpc_http_failure")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ProviderError("rpc_response_encoding_invalid")
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=16_384):
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES or time.monotonic() - started > self._timeout:
                        raise ProviderError("rpc_response_limit_exceeded")
            body = json.loads(raw)
            if (not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or body.get("id") != request_id
                    or ("result" in body) == ("error" in body)):
                raise ProviderError("rpc_invalid_response")
            if "error" in body:
                raise ProviderError("rpc_rejected")
            return body["result"]
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise ProviderError("rpc_unavailable_or_invalid_response") from None

    def close(self):
        self._client.close()


class LocalFileSigner:
    def __init__(self, path, allowed_publisher):
        self._path = path
        self._publisher = allowed_publisher

    def configured(self):
        """Metadata only; private key bytes are not read for capabilities."""
        try:
            info = os.lstat(self._path)
            return (stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077
                    and info.st_uid == os.getuid() and 129 <= info.st_size <= 4096)
        except OSError:
            return False

    def sign_message(self, message):
        from solders.keypair import Keypair
        descriptor = None
        try:
            descriptor = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid()
                    or info.st_size > 4096):
                raise ValueError()
            raw = os.read(descriptor, 4097)
            values = json.loads(raw)
            if (not isinstance(values, list) or len(values) != 64
                    or any(type(value) is not int or not 0 <= value <= 255 for value in values)):
                raise ValueError()
            signer = Keypair.from_bytes(bytes(values))
            if str(signer.pubkey()) != self._publisher:
                raise ValueError()
            return signer.sign_message(message)
        except (OSError, ValueError, TypeError):
            raise ProviderError("publisher_key_invalid_or_not_authorized") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)


def adapter_from_environment():
    """No RPC calls or key loading, including when SOLANA_ENABLED=false."""
    config = LiveConfig.from_environment()
    signer = LocalFileSigner(config.keypair_path, config.publisher)
    return MemoAdapter(MemoConfig(config.publisher, max_fee_lamports=config.max_fee_lamports),
        JsonRpcClient(config.rpc_url, config.timeout_seconds), signer,
        verification_rpc=JsonRpcClient(config.verify_rpc_url, config.timeout_seconds))
