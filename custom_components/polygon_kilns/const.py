"""Constants for the Polygon Kilns integration."""

from datetime import timedelta

DOMAIN = "polygon_kilns"

# Firebase project configuration of the official Polygon backend.
# The API key identifies the Firebase project; it is not a secret. Access is
# governed by Firebase Auth and Firestore security rules.
FIREBASE_API_KEY = "AIzaSyDfZHpmUyTzWv-TQmevcvfd-zKYo1adbAU"
FIREBASE_PROJECT_ID = "polygonkilns"

FIREBASE_AUTH_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
)
FIREBASE_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"
FIRESTORE_BASE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
    "/databases/(default)/documents"
)
REQUEST_START_URL = "https://us-central1-polygonkilns.cloudfunctions.net/requestStart"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_UID = "uid"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_POLL_INTERVAL = 30
MIN_POLL_INTERVAL = 15
MAX_POLL_INTERVAL = 120

# Refresh the Firebase ID token when less than this much lifetime remains.
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

# A kiln is considered offline if its lastSeen is older than this.
OFFLINE_AFTER = timedelta(minutes=5)

# Kiln states in which a new program can be started.
STARTABLE_STATES = ("en espera", "idle", "finished", "terminado")

ATTR_KILN_ID = "kiln_id"
ATTR_SCHED_NUM = "sched_num"
ATTR_SCHEDULE_NAME = "schedule_name"
ATTR_START_TIME = "start_time"
ATTR_STAGES = "stages"

SERVICE_START_SCHEDULE = "start_schedule"
SERVICE_STOP_SCHEDULE = "stop_schedule"
SERVICE_CREATE_SCHEDULE = "create_schedule"
SERVICE_UPDATE_SCHEDULE = "update_schedule"
SERVICE_DELETE_SCHEDULE = "delete_schedule"
