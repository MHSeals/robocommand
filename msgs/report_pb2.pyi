"""
Type stubs for msgs/report_pb2.py (generated protobuf code).
Pylance cannot statically analyse the dynamic builder pattern used by the
protobuf runtime, so these stubs expose all symbols explicitly.
"""

from typing import Optional
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp

# ---------------------------------------------------------------------------
# Enums
# Each enum is an int subclass at runtime.  The class-level constants and the
# Name() / Value() helpers mirror the protobuf Python API.
# ---------------------------------------------------------------------------

class RobotState(int):
    STATE_UNKNOWN: RobotState
    STATE_KILLED: RobotState
    STATE_MANUAL: RobotState
    STATE_AUTO: RobotState
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> RobotState: ...

STATE_UNKNOWN: RobotState
STATE_KILLED: RobotState
STATE_MANUAL: RobotState
STATE_AUTO: RobotState

class TaskType(int):
    TASK_UNKNOWN: TaskType
    TASK_NONE: TaskType
    TASK_ENTRY_EXIT: TaskType
    TASK_NAV_CHANNEL: TaskType
    TASK_SPEED_CHALLENGE: TaskType
    TASK_OBJECT_DELIVERY: TaskType
    TASK_DOCKING: TaskType
    TASK_SOUND_SIGNAL: TaskType
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> TaskType: ...

TASK_UNKNOWN: TaskType
TASK_NONE: TaskType
TASK_ENTRY_EXIT: TaskType
TASK_NAV_CHANNEL: TaskType
TASK_SPEED_CHALLENGE: TaskType
TASK_OBJECT_DELIVERY: TaskType
TASK_DOCKING: TaskType
TASK_SOUND_SIGNAL: TaskType

class ObjectType(int):
    OBJECT_UNKNOWN: ObjectType
    OBJECT_BOAT: ObjectType
    OBJECT_LIGHT_BEACON: ObjectType
    OBJECT_BUOY: ObjectType
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> ObjectType: ...

OBJECT_UNKNOWN: ObjectType
OBJECT_BOAT: ObjectType
OBJECT_LIGHT_BEACON: ObjectType
OBJECT_BUOY: ObjectType

class Color(int):
    COLOR_UNKNOWN: Color
    COLOR_YELLOW: Color
    COLOR_BLACK: Color
    COLOR_RED: Color
    COLOR_GREEN: Color
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> Color: ...

COLOR_UNKNOWN: Color
COLOR_YELLOW: Color
COLOR_BLACK: Color
COLOR_RED: Color
COLOR_GREEN: Color

class GateType(int):
    GATE_UNKNOWN: GateType
    GATE_ENTRY: GateType
    GATE_EXIT: GateType
    GATE_SPEED_START: GateType
    GATE_SPEED_END: GateType
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> GateType: ...

GATE_UNKNOWN: GateType
GATE_ENTRY: GateType
GATE_EXIT: GateType
GATE_SPEED_START: GateType
GATE_SPEED_END: GateType

class SignalType(int):
    SIGNAL_UNKNOWN: SignalType
    SIGNAL_ONE_BLAST: SignalType
    SIGNAL_TWO_BLAST: SignalType
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> SignalType: ...

SIGNAL_UNKNOWN: SignalType
SIGNAL_ONE_BLAST: SignalType
SIGNAL_TWO_BLAST: SignalType

class DeliveryType(int):
    DELIVERY_UNKNOWN: DeliveryType
    DELIVERY_WATER: DeliveryType
    DELIVERY_BALL: DeliveryType
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> DeliveryType: ...

DELIVERY_UNKNOWN: DeliveryType
DELIVERY_WATER: DeliveryType
DELIVERY_BALL: DeliveryType

class PatrolBoatActionType(int):
    PATROL_BOAT_ACTION_UNKNOWN: PatrolBoatActionType
    PATROL_BOAT_ACTION_STOPPING: PatrolBoatActionType
    PATROL_BOAT_ACTION_RESUMING: PatrolBoatActionType
    @classmethod
    def Name(cls, number: int) -> str: ...
    @classmethod
    def Value(cls, name: str) -> PatrolBoatActionType: ...

PATROL_BOAT_ACTION_UNKNOWN: PatrolBoatActionType
PATROL_BOAT_ACTION_STOPPING: PatrolBoatActionType
PATROL_BOAT_ACTION_RESUMING: PatrolBoatActionType

# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class LatLng(Message):
    latitude: float
    longitude: float
    def __init__(
        self,
        *,
        latitude: float = ...,
        longitude: float = ...,
    ) -> None: ...

class Heartbeat(Message):
    state: RobotState
    position: LatLng
    spd_mps: float
    heading_deg: float
    current_task: TaskType
    def __init__(
        self,
        *,
        state: int = ...,
        position: Optional[LatLng] = ...,
        spd_mps: float = ...,
        heading_deg: float = ...,
        current_task: int = ...,
    ) -> None: ...

class ObjectDetected(Message):
    object_type: ObjectType
    color: Color
    position: LatLng
    object_id: int
    task_context: TaskType
    def __init__(
        self,
        *,
        object_type: int = ...,
        color: int = ...,
        position: Optional[LatLng] = ...,
        object_id: int = ...,
        task_context: int = ...,
    ) -> None: ...

class GatePass(Message):
    type: GateType
    position: LatLng
    def __init__(
        self,
        *,
        type: int = ...,
        position: Optional[LatLng] = ...,
    ) -> None: ...

class ObjectDelivery(Message):
    vessel_color: Color
    position: LatLng
    delivery_type: DeliveryType
    def __init__(
        self,
        *,
        vessel_color: int = ...,
        position: Optional[LatLng] = ...,
        delivery_type: int = ...,
    ) -> None: ...

class Docking(Message):
    dock: str
    slip: str
    def __init__(
        self,
        *,
        dock: str = ...,
        slip: str = ...,
    ) -> None: ...

class SoundSignal(Message):
    signal_type: SignalType
    frequency_hz: int
    assigned_task: TaskType
    def __init__(
        self,
        *,
        signal_type: int = ...,
        frequency_hz: int = ...,
        assigned_task: int = ...,
    ) -> None: ...

class PatrolBoat(Message):
    patrol_boat_action_type: PatrolBoatActionType
    def __init__(
        self,
        *,
        patrol_boat_action_type: int = ...,
    ) -> None: ...

class Report(Message):
    team_id: str
    vehicle_id: str
    seq: int
    sent_at: Timestamp
    # oneof body
    heartbeat: Heartbeat
    object_detected: ObjectDetected
    gate_pass: GatePass
    object_delivery: ObjectDelivery
    docking: Docking
    sound_signal: SoundSignal
    patrol_boat: PatrolBoat
    def __init__(
        self,
        *,
        team_id: str = ...,
        vehicle_id: str = ...,
        seq: int = ...,
        sent_at: Optional[Timestamp] = ...,
        heartbeat: Optional[Heartbeat] = ...,
        object_detected: Optional[ObjectDetected] = ...,
        gate_pass: Optional[GatePass] = ...,
        object_delivery: Optional[ObjectDelivery] = ...,
        docking: Optional[Docking] = ...,
        sound_signal: Optional[SoundSignal] = ...,
        patrol_boat: Optional[PatrolBoat] = ...,
    ) -> None: ...
    def WhichOneof(self, oneof_group: str) -> Optional[str]: ...
