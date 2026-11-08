"""Strict legacy Memo transactions over mockable RPC/signing ports."""
import base64
from dataclasses import dataclass

MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
# Pin the cluster, not merely an RPC URL supplied by a client.
DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"


class ProviderError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class InvalidTransaction(ValueError):
    pass


def verify_signatures(transaction):
    transaction.verify()


@dataclass(frozen=True)
class MemoConfig:
    publisher: str
    genesis_hash: str = DEVNET_GENESIS
    max_fee_lamports: int = 10_000

    def __post_init__(self):
        from solders.pubkey import Pubkey
        Pubkey.from_string(self.publisher)
        if self.genesis_hash != DEVNET_GENESIS:
            raise ValueError("Only Solana Devnet is supported")
        if type(self.max_fee_lamports) is not int or not 1 <= self.max_fee_lamports <= 100_000:
            raise ValueError("Invalid transaction fee limit")


class MemoAdapter:
    def __init__(self, config: MemoConfig, rpc, signer, *, verification_rpc=None):
        self.config, self.rpc, self.signer = config, rpc, signer
        self.verification_rpc = verification_rpc or rpc

    def network(self, rpc=None):
        if (rpc or self.rpc).call("getGenesisHash", []) != self.config.genesis_hash:
            raise InvalidTransaction("RPC network mismatch")

    def configured(self):
        return self.signer is not None and (not hasattr(self.signer, "configured") or self.signer.configured())

    def close(self):
        for rpc in {self.rpc, self.verification_rpc}:
            if hasattr(rpc, "close"):
                rpc.close()

    def binding(self, proof):
        envelope = proof["bundle"]["envelope"]
        if (envelope["proof_id"] != proof["proof_id"] or envelope["publisher"] != self.config.publisher
                or envelope["network_genesis_hash"] != self.config.genesis_hash
                or envelope["memo_program"] != MEMO_PROGRAM or proof["genesis_hash"] != self.config.genesis_hash):
            raise InvalidTransaction("Proof network/signer binding mismatch")

    def fee(self, message, maximum=None):
        fee = self.rpc.call("getFeeForMessage", [base64.b64encode(bytes(message)).decode("ascii"),
                                                {"commitment": "finalized"}])["value"]
        limit = min(self.config.max_fee_lamports, maximum or self.config.max_fee_lamports)
        if type(fee) is not int or not 1 <= fee <= limit:
            raise ProviderError("transaction_fee_unavailable_or_exceeds_limit")
        return fee

    @staticmethod
    def memo(proof):
        return f"FactoryOS RepairProof v1 | {proof['proof_id']} | {proof['bundle']['commitment']}".encode("utf-8")

    def inspect(self, raw: str, proof: dict, signature: str | None = None):
        from solders.transaction import Transaction
        try:
            self.binding(proof)
            wire = base64.b64decode(raw, validate=True)
            if len(wire) > 1232:
                raise ValueError()
            transaction = Transaction.from_bytes(wire)
            transaction.sanitize()
            if bytes(transaction) != wire:
                raise ValueError()
            verify_signatures(transaction)
            message = transaction.message
            instructions = message.instructions
            if (message.header.num_required_signatures != 1
                    or message.header.num_readonly_signed_accounts != 0
                    or message.header.num_readonly_unsigned_accounts != 1
                    or [str(key) for key in message.account_keys] != [self.config.publisher, MEMO_PROGRAM]
                    or len(instructions) != 1
                    or instructions[0].program_id_index != 1
                    or bytes(instructions[0].accounts) != b"\x00"
                    or bytes(instructions[0].data) != self.memo(proof)
                    or len(transaction.signatures) != 1
                    or (signature is not None and str(transaction.signatures[0]) != signature)):
                raise ValueError()
            return transaction
        except Exception:
            raise InvalidTransaction("Invalid signed Memo transaction") from None

    def prepare(self, proof):
        from solders.hash import Hash
        from solders.instruction import AccountMeta, Instruction
        from solders.message import Message
        from solders.pubkey import Pubkey
        from solders.transaction import Transaction
        self.binding(proof)
        self.network()
        latest = self.rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])["value"]
        publisher = Pubkey.from_string(self.config.publisher)
        instruction = Instruction(Pubkey.from_string(MEMO_PROGRAM), self.memo(proof),
                                  [AccountMeta(publisher, True, False)])
        message = Message.new_with_blockhash([instruction], publisher, Hash.from_string(latest["blockhash"]))
        if type(latest["lastValidBlockHeight"]) is not int or latest["lastValidBlockHeight"] < 1:
            raise ProviderError("invalid_blockhash_expiry")
        fee = self.fee(message)
        balance = self.rpc.call("getBalance", [self.config.publisher, {"commitment": "finalized"}])["value"]
        if type(balance) is not int or balance < fee:
            raise ProviderError("insufficient_devnet_balance")
        if not self.configured():
            raise ProviderError("publisher_key_unavailable")
        transaction = Transaction.populate(message, [self.signer.sign_message(bytes(message))])
        raw = base64.b64encode(bytes(transaction)).decode("ascii")
        self.inspect(raw, proof)
        return {"signed_transaction_b64": raw, "signature": str(transaction.signatures[0]),
                "blockhash": latest["blockhash"], "last_valid_block_height": latest["lastValidBlockHeight"],
                "estimated_fee_lamports": fee, "max_fee_lamports": self.config.max_fee_lamports}

    def submit(self, proof):
        self.network()
        transaction = self.inspect(proof["signed_transaction_b64"], proof, proof["signature"])
        if str(transaction.message.recent_blockhash) != proof["blockhash"]:
            raise InvalidTransaction("Saved blockhash mismatch")
        height = self.rpc.call("getBlockHeight", [{"commitment": "finalized"}])
        if type(height) is not int or height > proof["last_valid_block_height"]:
            raise ProviderError("blockhash_expired_or_unavailable")
        self.fee(transaction.message, proof["max_fee_lamports"])
        signature = self.rpc.call("sendTransaction", [proof["signed_transaction_b64"],
            {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "finalized", "maxRetries": 0}])
        if signature != proof["signature"]:
            raise InvalidTransaction("Provider returned an unexpected signature")

    def verify(self, proof):
        self.binding(proof)
        rpc = self.verification_rpc
        self.network(rpc)
        statuses = rpc.call("getSignatureStatuses", [[proof["signature"]], {"searchTransactionHistory": True}])
        status = statuses["value"][0]
        if status is None:
            return {"status": "UNKNOWN", "reason": "signature_not_found"}
        if status.get("err") is not None:
            return {"status": "CHAIN_FAILED", "reason": "transaction_failed"}
        if status.get("confirmationStatus") != "finalized":
            return {"status": "PENDING", "reason": "not_finalized"}
        receipt = rpc.call("getTransaction", [proof["signature"],
            {"encoding": "base64", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
        if receipt is None:
            return {"status": "UNKNOWN", "reason": "transaction_not_available"}
        if receipt.get("meta") is None or receipt["meta"].get("err") is not None:
            raise InvalidTransaction("Transaction execution not successful")
        fee = receipt["meta"].get("fee")
        if (type(fee) is not int or not 0 <= fee <= min(self.config.max_fee_lamports, proof.get("max_fee_lamports", self.config.max_fee_lamports))
                or type(receipt.get("slot")) is not int or receipt["slot"] <= 0
                or (status.get("slot") is not None and status["slot"] != receipt["slot"])):
            raise InvalidTransaction("Transaction fee or slot mismatch")
        raw, encoding = receipt["transaction"]
        if encoding != "base64" or raw != proof["signed_transaction_b64"]:
            raise InvalidTransaction("Transaction bytes mismatch")
        self.inspect(raw, proof, proof["signature"])
        return {"status": "FINALIZED", "reason": "commitment_matches", "slot": receipt["slot"],
                "fee_lamports": fee, "signer": self.config.publisher, "network": "devnet", "commitment": proof["bundle"]["commitment"]}
