"""Typed agent messages used by the coordinator."""
from dataclasses import dataclass, field
from typing import Any
import json
@dataclass
class Message:
    sender: str
    receiver: str
    round: int
    payload: dict[str, Any] = field(default_factory=dict)
class PriceSignal(Message): pass
class FlexBid(Message): pass
class P2POffer(Message): pass
class P2PBid(Message): pass
class Accept(Message): pass
class Reject(Message): pass

MESSAGE_TYPES = {cls.__name__: cls for cls in (PriceSignal, FlexBid, P2POffer, P2PBid, Accept, Reject)}

def encode_message(message: Message) -> str:
    """Serialize a protocol message as canonical JSON for event logs."""
    return json.dumps({"type": type(message).__name__, "sender": message.sender, "receiver": message.receiver,
                       "round": message.round, "payload": message.payload}, sort_keys=True, separators=(",", ":"))

def decode_message(record: str | dict[str, Any]) -> Message:
    """Parse and validate a serialized protocol message."""
    data = json.loads(record) if isinstance(record, str) else dict(record)
    kind = data.get("type")
    if kind not in MESSAGE_TYPES:
        raise ValueError(f"Unknown message type: {kind}")
    if not isinstance(data.get("sender"), str) or not isinstance(data.get("receiver"), str):
        raise ValueError("sender and receiver must be strings")
    if not isinstance(data.get("round"), int) or data["round"] < 0:
        raise ValueError("round must be a nonnegative integer")
    if not isinstance(data.get("payload"), dict):
        raise ValueError("payload must be an object")
    return MESSAGE_TYPES[kind](data["sender"], data["receiver"], data["round"], data["payload"])
