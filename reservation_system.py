import threading
import queue
import time
import uuid
import random
from dataclasses import dataclass
from typing import List, Dict, Optional

NUM_SLOTS = 10
HOLD_SECONDS = 5
VALIDATOR_WORKERS = 2
PROCESSOR_WORKERS = 1
REQUESTER_THREADS = 6
SIMULATION_SECONDS = 20

incoming_queue = queue.Queue()
confirm_queue = queue.Queue()

slot_locks: Dict[int, threading.Lock] = {}
slots: Dict[int, Dict] = {}

holds: Dict[str, Dict] = {}
global_state_lock = threading.Lock()

@dataclass
class ReserveRequest:
    user: str
    slot_ids: List[int]
    request_id: str = None

@dataclass
class ConfirmRequest:
    user: str
    hold_id: str

def init_system():
    for i in range(NUM_SLOTS):
        slot_locks[i] = threading.Lock()
        slots[i] = {'state': 'FREE', 'held_by': None, 'hold_id': None, 'expires': None}

def acquire_locks_ordered(slot_ids: List[int], timeout=1.0) -> bool:
    ordered = sorted(slot_ids)
    acquired = []
    start = time.time()
    for s in ordered:
        remaining = timeout - (time.time() - start)
        if remaining <= 0:
            for a in acquired:
                a.release()
            return False
        got = slot_locks[s].acquire(timeout=remaining)
        if not got:
            for a in acquired:
                a.release()
            return False
        acquired.append(slot_locks[s])
    return True

def release_locks_ordered(slot_ids: List[int]):
    for s in sorted(slot_ids, reverse=True):
        if slot_locks[s].locked():
            try:
                slot_locks[s].release()
            except RuntimeError:
                pass

class ValidatorThread(threading.Thread):
    def __init__(self, wid:int):
        super().__init__(daemon=True)
        self.wid = wid

    def run(self):
        while True:
            try:
                req: ReserveRequest = incoming_queue.get(timeout=1)
            except queue.Empty:
                continue
            if not all(0 <= s < NUM_SLOTS for s in req.slot_ids):
                continue

            got_all = acquire_locks_ordered(req.slot_ids, timeout=1.0)
            if not got_all:
                continue

            with global_state_lock:
                conflict = False
                for s in req.slot_ids:
                    if slots[s]['state'] != 'FREE':
                        conflict = True
                        break
                if conflict:
                    release_locks_ordered(req.slot_ids)
                    continue

                hold_id = str(uuid.uuid4())
                expires = time.time() + HOLD_SECONDS
                for s in req.slot_ids:
                    slots[s]['state'] = 'HELD'
                    slots[s]['held_by'] = req.user
                    slots[s]['hold_id'] = hold_id
                    slots[s]['expires'] = expires
                holds[hold_id] = {'user': req.user, 'slots': list(req.slot_ids), 'expires': expires}

            release_locks_ordered(req.slot_ids)
            incoming_queue.task_done()

class ProcessorThread(threading.Thread):
    def __init__(self, wid:int):
        super().__init__(daemon=True)
        self.wid = wid

    def run(self):
        while True:
            try:
                c: ConfirmRequest = confirm_queue.get(timeout=1)
            except queue.Empty:
                continue

            hold = holds.get(c.hold_id)
            if not hold:
                confirm_queue.task_done()
                continue

            if hold['user'] != c.user:
                confirm_queue.task_done()
                continue

            slot_ids = hold['slots']
            got_all = acquire_locks_ordered(slot_ids, timeout=1.0)
            if not got_all:
                confirm_queue.task_done()
                continue

            with global_state_lock:
                now = time.time()
                if hold['expires'] < now:
                    release_locks_ordered(slot_ids)
                    confirm_queue.task_done()
                    continue

                conflict = False
                for s in slot_ids:
                    if slots[s]['state'] != 'HELD' or slots[s]['hold_id'] != c.hold_id:
                        conflict = True
                        break
                if conflict:
                    release_locks_ordered(slot_ids)
                    confirm_queue.task_done()
                    continue

                for s in slot_ids:
                    slots[s]['state'] = 'BOOKED'
                    slots[s]['held_by'] = c.user
                    slots[s]['hold_id'] = c.hold_id
                    slots[s]['expires'] = None
                del holds[c.hold_id]

            release_locks_ordered(slot_ids)
            confirm_queue.task_done()

class ExpiratorThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)

    def run(self):
        while True:
            time.sleep(1)
            now = time.time()
            expired = []
            with global_state_lock:
                for hid, info in list(holds.items()):
                    if info['expires'] < now:
                        expired.append((hid, info))
                for hid, info in expired:
                    for s in info['slots']:
                        if slot_locks[s].acquire(timeout=0.2):
                            try:
                                if slots[s]['hold_id'] == hid and slots[s]['state'] == 'HELD':
                                    slots[s]['state'] = 'FREE'
                                    slots[s]['held_by'] = None
                                    slots[s]['hold_id'] = None
                                    slots[s]['expires'] = None
                            finally:
                                slot_locks[s].release()
                    if hid in holds:
                        del holds[hid]

class RequesterThread(threading.Thread):
    def __init__(self, user_id:int):
        super().__init__(daemon=True)
        self.user = f"user{user_id}"
        self.rng = random.Random(user_id + int(time.time()))

    def run(self):
        while True:
            time.sleep(self.rng.uniform(0.1, 1.0))
            k = self.rng.choice([1, 1, 2])
            slots_req = self.rng.sample(range(NUM_SLOTS), k)
            req = ReserveRequest(user=self.user, slot_ids=slots_req, request_id=str(uuid.uuid4()))
            incoming_queue.put(req)
            will_confirm = self.rng.random() < 0.6
            if will_confirm:
                time.sleep(self.rng.uniform(0.1, 2.0))
                with global_state_lock:
                    candidate = None
                    for hid, info in holds.items():
                        if info['user'] == self.user and set(info['slots']) == set(slots_req):
                            candidate = hid
                            break
                if candidate:
                    confirm_queue.put(ConfirmRequest(user=self.user, hold_id=candidate))

def print_state():
    with global_state_lock:
        s = []
        for i in range(NUM_SLOTS):
            st = slots[i]['state']
            owner = slots[i]['held_by'] or '-'
            h = (slots[i]['hold_id'][:8] if slots[i]['hold_id'] else '-')
            s.append(f"{i}:{st[:1]}({owner},{h})")
        print("SLOTS:", " | ".join(s))
        print("Active holds:", {k[:8]:v for k, v in holds.items()})

def main():
    init_system()
    for i in range(VALIDATOR_WORKERS):
        ValidatorThread(wid=i).start()
    for i in range(PROCESSOR_WORKERS):
        ProcessorThread(wid=i).start()
    ExpiratorThread().start()
    for i in range(REQUESTER_THREADS):
        RequesterThread(i).start()

    start = time.time()
    try:
        while time.time() - start < SIMULATION_SECONDS:
            time.sleep(2)
            print_state()
    except KeyboardInterrupt:
        pass
    print("\nSimulation finished. Final state:")
    print_state()

if __name__ == "__main__":
    main()
