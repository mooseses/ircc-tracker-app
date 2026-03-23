"""
tracker.py — Core IRCC API logic
"""

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Constants ────────────────────────────────────────────────────────────────

COGNITO_REGION = "ca-central-1"
CLIENT_ID = "3cfutv5ffd1i622g1tn6vton5r"
COGNITO_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
API_URL = "https://api.ircc-tracker-suivi.apps.cic.gc.ca/user"
HISTORY_MAP_URL = "https://ircc-tracker-suivi.apps.cic.gc.ca/assets/corr-history-map.json"


# ─── Auth ─────────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> dict:
    """Authenticate via AWS Cognito. Returns AuthenticationResult dict."""
    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    }
    payload = {
        "AuthFlow": "USER_PASSWORD_AUTH",
        "ClientId": CLIENT_ID,
        "AuthParameters": {
            "USERNAME": username,
            "PASSWORD": password,
        },
    }
    resp = requests.post(COGNITO_URL, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Authentication failed ({resp.status_code}): {resp.text}")
    return resp.json()["AuthenticationResult"]


# ─── API Calls ────────────────────────────────────────────────────────────────

def _api_headers(id_token: str) -> dict:
    return {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://ircc-tracker-suivi.apps.cic.gc.ca",
        "Referer": "https://ircc-tracker-suivi.apps.cic.gc.ca/",
    }


def fetch_profile_summary(id_token: str) -> dict:
    """Fetch full profile summary (includes all applications)."""
    resp = requests.post(
        API_URL,
        headers=_api_headers(id_token),
        json={"method": "get-profile-summary"},
        timeout=30,
        verify=False,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Profile fetch failed ({resp.status_code}): {resp.text}")
    return resp.json()


def fetch_applications(id_token: str) -> list:
    """Fetch list of applications linked to the account."""
    try:
        data = fetch_profile_summary(id_token)
    except Exception:
        return []

    # The profile summary may wrap apps in different keys
    if isinstance(data, list):
        return data
    # Try common response shapes
    for key in ("applications", "apps", "data"):
        if key in data and isinstance(data[key], list):
            return data[key]
    # If the response is a dict with app-like keys, wrap it
    if "appNumber" in data:
        return [data]
    return [data] if data else []


def fetch_application_detail(id_token: str, app_number: str, uci: str) -> dict:
    """Fetch full details for one application."""
    resp = requests.post(
        API_URL,
        headers=_api_headers(id_token),
        json={
            "method": "get-application-details",
            "applicationNumber": app_number,
            "uci": uci,
            "isAgent": False,
        },
        timeout=30,
        verify=False,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API error ({resp.status_code}): {resp.text}")
    return resp.json()


def fetch_history_map() -> dict:
    """Fetch corr-history-map.json from the IRCC CDN (fresh every call)."""
    try:
        resp = requests.get(HISTORY_MAP_URL, timeout=15, verify=False)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    # Fallback hardcoded map in case the CDN is unreachable
    return {
        "28": "BIRTH_CERT", "29": "DIVORCE_CERT", "31": "CUSTODY",
        "41": "PASSPORT", "42": "PASSPORT_PHOTO", "54": "MED_PROOF",
        "57": "POLICE_CERT", "61": "FAMILY_INFO", "63": "USE_OF_REP",
        "65": "GEN_APPL_FORM", "70": "CORRESPONDENCE", "86": "PHOTO",
        "89": "TRAVEL_DOC", "96": "WITHDRAWAL", "437": "ADD_FEES",
        "602": "SPR_INFO", "609": "SPR_UNDERTAKING", "651": "RELATIONSHIP",
        "664": "PAYMENT", "667": "MARRIAGE_CERT", "709": "SCHEDULE_A",
        "723": "ADD_FAMILY_INFO", "871": "POLICE_CERT", "873": "PASSPORT",
        "959": "APPLICATION_RECEIVED", "960": "FEES_RECEIVED",
        "1021": "ENQUIRY", "1290": "APPLICATION_TRANSFER", "1319": "IMM_DOCS",
        "Word LTR 01": "AOR", "Auto E-mail 01": "AOR",
        "Auto E-mail 20": "COPR_ISSUED",
        "Auto E-mail 111": "BIOMETRICS", "IMM5756": "BIOMETRIC_FEES",
        "Word LTR 20": "COPR_ISSUED", "Word LTR 29": "ELIG_DEC",
        "Word LTR 11": "ELIG_DEC", "IMM1017": "MED_REPORT",
        "IMM5706": "MED_ADD", "IMM0535": "MED_RESULT",
        "Auto E-mail 108": "PREARRIVAL", "IMM5801": "PREARRIVAL",
        "Word LTR 28": "PR_AUTH", "Word LTR 24": "REFUND_FEES",
        "Word LTR 21": "SPR_DEC", "Word LTR 22": "SPR_DEC",
        "Word LTR 19": "TRANSFERRED", "Word LTR 12": "WITHDRAWN",
        "INITIAL": "INITIAL", "Medical": "MEDICAL_UPDATE",
    }


# ─── Human-Readable Labels ───────────────────────────────────────────────────

HUMAN_LABELS = {
    "INITIAL": "Application Received",
    "APPLICATION_RECEIVED": "Application Received",
    "AOR": "Acknowledgement of Receipt",
    "BIOMETRICS": "Biometrics Request",
    "BIOMETRIC_FEES": "Biometric Fees",
    "MEDICAL_UPDATE": "Medical Update",
    "MED_PROOF": "Medical Proof",
    "MED_REPORT": "Medical Report",
    "MED_ADD": "Medical Additional Info",
    "MED_RESULT": "Medical Result",
    "ENQUIRY": "Enquiry",
    "BIRTH_CERT": "Birth Certificate",
    "DIVORCE_CERT": "Divorce Certificate",
    "CUSTODY": "Custody Document",
    "PASSPORT": "Passport",
    "PASSPORT_PHOTO": "Passport Photo",
    "POLICE_CERT": "Police Certificate",
    "FAMILY_INFO": "Family Information",
    "USE_OF_REP": "Use of Representative",
    "GEN_APPL_FORM": "General Application Form",
    "WITHDRAWAL": "Withdrawal",
    "ADD_FEES": "Additional Fees",
    "SPR_INFO": "Sponsor Information",
    "SPR_UNDERTAKING": "Sponsor Undertaking",
    "SPR_DEC": "Sponsor Decision",
    "RELATIONSHIP": "Relationship Document",
    "PAYMENT": "Payment Received",
    "MARRIAGE_CERT": "Marriage Certificate",
    "ADD_FAMILY_INFO": "Additional Family Information",
    "COPR_ISSUED": "COPR Issued",
    "ELIG_DEC": "Eligibility Decision",
    "PREARRIVAL": "Pre-Arrival Services",
    "PR_AUTH": "PR Authorization",
    "REFUND_FEES": "Fee Refund",
    "TRANSFERRED": "File Transferred",
    "WITHDRAWN": "Application Withdrawn",
    "CORRESPONDENCE": "Correspondence",
    "PHOTO": "Photograph",
    "TRAVEL_DOC": "Travel Document",
    "SCHEDULE_A": "Schedule A",
    "FEES_RECEIVED": "Fees Received",
    "APPLICATION_TRANSFER": "Application Transfer",
    "IMM_DOCS": "Immigration Documents",
}


def decode_history_key(key: str, history_map: dict) -> str:
    """Convert a raw history key to a human-readable label."""
    code = history_map.get(key, key)
    return HUMAN_LABELS.get(code, code.replace("_", " ").title())
