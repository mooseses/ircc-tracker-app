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


def refresh_id_token(refresh_token: str) -> dict:
    """Use a Cognito refresh token to obtain a fresh IdToken without re-entering credentials."""
    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    }
    payload = {
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "ClientId": CLIENT_ID,
        "AuthParameters": {"REFRESH_TOKEN": refresh_token},
    }
    resp = requests.post(COGNITO_URL, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): {resp.text}")
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
    """Fetch corr-history-map.json from the IRCC CDN and merge with hardcoded base.

    The CDN map is authoritative but incomplete — it omits several numeric keys
    that the API does return (e.g. "70", "86", "89", "709", "959", "960", "1290",
    "1319"). We always start from the full hardcoded base and overlay CDN data on
    top so that all known keys are covered regardless of CDN availability.
    """
    base = {
        # Numeric codes
        "28": "BIRTH_CERT", "29": "DIVORCE_CERT", "31": "CUSTODY",
        "41": "PASSPORT", "42": "PASSPORT_PHOTO", "54": "MED_PROOF",
        "57": "POLICE_CERT", "61": "FAMILY_INFO", "63": "USE_OF_REP",
        "65": "GEN_APPL_FORM", "70": "INFO_RECEIVED", "86": "PHOTO",
        "89": "TRAVEL_DOC", "96": "WITHDRAWAL", "437": "ADD_FEES",
        "602": "SPR_INFO", "609": "SPR_UNDERTAKING", "651": "RELATIONSHIP",
        "664": "PAYMENT", "667": "MARRIAGE_CERT", "709": "SCHEDULE_A",
        "723": "ADD_FAMILY_INFO", "871": "POLICE_CERT", "873": "PASSPORT",
        "959": "APPLICATION_RECEIVED", "960": "FEES_RECEIVED",
        "1021": "ENQUIRY", "1290": "APPLICATION_TRANSFER", "1319": "IMM_DOCS",
        # Letter / e-mail codes
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
    try:
        resp = requests.get(HISTORY_MAP_URL, timeout=15, verify=False)
        if resp.status_code == 200:
            base.update(resp.json())
    except Exception:
        pass
    # Apply corrections for known CDN mapping errors
    # "Auto E-mail 20" is a generic correspondence email, NOT COPR
    base["Auto E-mail 20"] = "CORRESPONDENCE"
    return base


# ─── Human-Readable Labels ───────────────────────────────────────────────────

HUMAN_LABELS = {
    # Application milestones
    "INITIAL": "Application Received",
    "APPLICATION_RECEIVED": "Application Received",
    "AOR": "Acknowledgement of Receipt",
    "FEES_RECEIVED": "Fees Received",
    "COPR_ISSUED": "Confirmation of Permanent Residence (COPR) Issued",
    "ELIG_DEC": "Eligibility Decision",
    "PR_AUTH": "Permanent Resident Travel Authorization",
    "TRANSFERRED": "Application Transferred",
    "REFUND_FEES": "Fee Refund Issued",
    "WITHDRAWN": "Application Withdrawn",
    "WITHDRAWAL": "Application Withdrawal Requested",
    "APPLICATION_TRANSFER": "Application Transfer",
    # Action required
    "BIOMETRICS": "Complete Your Biometrics",
    "BIOMETRIC_FEES": "Biometric Fee Payment Required",
    "ADD_FEES": "Additional Fees Required",
    # Medical
    "MEDICAL_UPDATE": "Medical Exam",
    "MED_PROOF": "Medical Proof Received",
    "MED_REPORT": "Medical Report Received",
    "MED_ADD": "Additional Medical Information Requested",
    "MED_RESULT": "Medical Result Received",
    # Enquiries & correspondence
    "ENQUIRY": "We received your enquiry",
    "INFO_RECEIVED": "We received the information you sent us",
    "CORRESPONDENCE": "Message About Your Application",
    "IMM_DOCS": "Immigration Documents Received",
    # Documents received
    "BIRTH_CERT": "Birth Registration/Certificate Received",
    "DIVORCE_CERT": "Divorce Certificate Received",
    "CUSTODY": "Custody Document Received",
    "PASSPORT": "Passport/Travel Document Received",
    "PASSPORT_PHOTO": "Passport Photo Received",
    "TRAVEL_DOC": "Travel Document Received",
    "PHOTO": "Photograph Received",
    "POLICE_CERT": "Police Certificate Received",
    "MARRIAGE_CERT": "Marriage Certificate Received",
    "FAMILY_INFO": "Family Information Form Received",
    "ADD_FAMILY_INFO": "Additional Family Information (IMM 5406) Received",
    "USE_OF_REP": "Use of Representative Form Received",
    "GEN_APPL_FORM": "Generic Application Form for Canada (IMM 0008) Received",
    "SCHEDULE_A": "Schedule A Received",
    "RELATIONSHIP": "Relationship Document Received",
    "PAYMENT": "Payment Received",
    # Sponsorship
    "SPR_INFO": "Sponsor Information Received",
    "SPR_UNDERTAKING": "Sponsor Undertaking Received",
    "SPR_DEC": "Sponsorship Decision",
    # Other
    "PREARRIVAL": "Pre-Arrival Services",
    "Security": "Security Screening",
}


def decode_history_key(key: str, history_map: dict) -> str:
    """Convert a raw history key to a human-readable label."""
    code = history_map.get(key, key)
    return HUMAN_LABELS.get(code, code.replace("_", " ").title())
