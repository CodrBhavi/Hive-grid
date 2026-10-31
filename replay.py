"""Deterministic JSONL message-protocol recorder and replay tool."""
import argparse
import json
from pathlib import Path
from typing import Iterable
from messages import Message, decode_message, encode_message

class MessageBus:
    """In-memory protocol bus that records messages in delivery order."""
    def __init__(self): self.records: list[str] = []; self.inboxes: dict[str, list[Message]] = {}
    def send(self, message: Message) -> None:
        parsed = decode_message(encode_message(message))
        self.records.append(encode_message(parsed)); self.inboxes.setdefault(parsed.receiver, []).append(parsed)
    def receive(self, agent_id: str) -> list[Message]:
        """Drain one agent's inbox in recorded order."""
        return self.inboxes.pop(agent_id, [])

def replay(records: Iterable[str]) -> tuple[list[str], dict[str, list[Message]]]:
    """Replay protocol records with deterministic per-recipient delivery."""
    bus = MessageBus()
    for record in records: bus.send(decode_message(record))
    return bus.records, bus.inboxes

def extract_messages(line: str) -> list[str]:
    """Accept raw protocol rows, event rows, or an exported events envelope."""
    data=json.loads(line)
    if isinstance(data,dict) and 'type' in data: return [encode_message(decode_message(data))]
    events=data.get('events',[]) if isinstance(data,dict) else data if isinstance(data,list) else []
    output=[]
    for event in events:
        for message in event.get('messages',[]): output.append(encode_message(decode_message(message)))
    return output

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--input',default='data/messages.jsonl'); parser.add_argument('--output',default='data/replayed.jsonl'); parser.add_argument('--smoke',action='store_true'); args=parser.parse_args()
    source=Path(args.input)
    if args.smoke and not source.exists():
        from messages import PriceSignal, FlexBid
        bus=MessageBus(); bus.send(PriceSignal('GRID','SOCIETY',0,{'price':.18})); bus.send(FlexBid('HOME-1','SOCIETY',1,{'kw':.5}))
        records=bus.records
    else:
        if not source.exists(): raise SystemExit(f'Input does not exist: {source}')
        rows=[line for line in source.read_text(encoding='utf-8').splitlines() if line.strip()]
        records=[message for row in rows for message in extract_messages(row)]
    canonical, inboxes=replay(records); out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text('\n'.join(canonical)+('\n' if canonical else ''),encoding='utf-8')
    print(json.dumps({'messages_replayed':len(canonical),'recipients':sorted(inboxes),'output':str(out)}))
if __name__=='__main__': main()
