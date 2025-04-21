import enum
import enum

class T(enum.Enum):
    DISCOVERY = 0
    DISCOVERY_REP = 1
    HEARTBEAT = 2
    ELECTION = 3
    ELECTION_REP = 4
    MASTER = 5