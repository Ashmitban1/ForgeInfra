"""Majority-acknowledged reservations; never an alternative incident writer."""
from copy import deepcopy

from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


class ProofConflict(ValueError):
    pass


class ProofRepository:
    def __init__(self, database):
        self.collection = None
        self.incidents = None
        self.requests = None
        if database is not None:
            options = {"write_concern": WriteConcern(w="majority"), "read_concern": ReadConcern("majority")}
            self.collection = database.get_collection("repair_proofs", **options)
            self.incidents = database.get_collection("incidents", **options)
            self.requests = database.get_collection("repair_proof_requests", **options)

    def ensure_indexes(self):
        # Disabled feature startup must not introduce database writes/failures.
        # Index acknowledgement is required before any request/reservation write.
        self.requests.create_index("request_key", unique=True)
        self.collection.create_index("proof_id", unique=True)
        self.collection.create_index([("incident_identity", 1), ("decision_id", 1), ("genesis_hash", 1)], unique=True)
        self.collection.create_index("request_key", unique=True)

    @property
    def durable(self):
        return self.collection is not None

    def get(self, proof_id):
        if not self.durable:
            return None
        return self.collection.find_one({"proof_id": proof_id}, {"_id": 0})

    def latest(self, identity, decision_id=None):
        query = {"incident_identity": identity}
        if decision_id is not None:
            query["decision_id"] = decision_id
        return self.collection.find_one(query, {"_id": 0},
                                        sort=[("created_at", -1)]) if self.durable else None

    def bind_request(self, key, revision, proof_id):
        self.ensure_indexes()
        record = {"request_key": key, "request_revision": revision, "proof_id": proof_id}
        try:
            if not self.requests.insert_one(record).acknowledged:
                raise PyMongoError("Request not acknowledged")
        except DuplicateKeyError:
            pass
        stored = self.requests.find_one({"request_key": key}, {"_id": 0})
        if stored != {key: value for key, value in record.items() if key != "_id"}:
            raise ProofConflict("Idempotency key identifies another proof request")

    def frozen(self, incident):
        if not self.durable:
            raise PyMongoError("Durable proof storage required")
        stored = self.incidents.find_one({"incident_id": incident["incident_id"],
                                          "created_at": incident["created_at"], "device_id": incident["device_id"]})
        if stored is None or stored.get("approval") != incident.get("approval"):
            raise PyMongoError("Frozen approval readback failed")
        return deepcopy(stored["approval"])

    def reserve(self, proof):
        self.ensure_indexes()
        try:
            result = self.collection.insert_one(deepcopy(proof))
            if not result.acknowledged or self.get(proof["proof_id"]) is None:
                raise PyMongoError("Proof reservation not acknowledged")
            return self.get(proof["proof_id"]), True
        except DuplicateKeyError:
            previous = self.collection.find_one({"request_key": proof["request_key"]}, {"_id": 0})
            if previous and previous["request_revision"] != proof["request_revision"]:
                raise ProofConflict("Idempotency key identifies a different proof request") from None
            previous = previous or self.collection.find_one({key: proof[key] for key in (
                "incident_identity", "decision_id", "genesis_hash")}, {"_id": 0})
            if previous is None:
                raise ProofConflict("Proof reservation conflict") from None
            return previous, False

    def transition(self, proof_id, previous, changes):
        result = self.collection.update_one({"proof_id": proof_id, "status": previous},
                                             {"$set": deepcopy(changes)})
        if not result.acknowledged:
            raise PyMongoError("Proof transition not acknowledged")
        if result.matched_count != 1:
            raise ProofConflict("Proof changed concurrently; inspect the existing reservation")
        # A failed/ambiguous acknowledgement prevents all downstream broadcast.
        stored = self.get(proof_id)
        if stored is None or any(stored.get(key) != value for key, value in changes.items()):
            raise PyMongoError("Proof transition readback failed")
        return stored
