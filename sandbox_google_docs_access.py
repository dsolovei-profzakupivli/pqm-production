"""Read-only, identity-pinned SANDBOX access check for appeal templates."""
from __future__ import annotations

import json
import urllib.request

WARNING_TEMPLATE_ID = "1Nebc4MJerGuU7QlY-8nk7jWNOBOwaszlqmkrZzo0de4"
DECLINE_1_2_TEMPLATE_ID = "1IclKZui5_EEg9JV-gA-v-8Lm7rrN32V2CsysPUQr1a0"
DECLINE_3_TEMPLATE_ID = "1gVoNkbCWh2cXsmgU3LaoA0vRTOLZZR5e0QQ6dYOG4QM"
SANDBOX_FOLDER_ID = "1pT7R9CiWNWAG0siz2aeasF0kiEYGSMFN"
WORKING_FOLDER_ID = "1V2mKBjcdmzEJzjETX6VCnKI6CS4IfvPp"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
METADATA_FIELDS = "id,name,mimeType,isAppAuthorized,capabilities(canCopy,canAddChildren)"

TEMPLATES = {
    "warning": WARNING_TEMPLATE_ID,
    "decline_p49_1_2": DECLINE_1_2_TEMPLATE_ID,
    "decline_p49_3": DECLINE_3_TEMPLATE_ID,
}


def metadata_url(file_id: str) -> str:
    if file_id not in {*TEMPLATES.values(), SANDBOX_FOLDER_ID}:
        raise PermissionError("SANDBOX Docs identity is not allowlisted")
    return (f"https://www.googleapis.com/drive/v3/files/{file_id}"
            f"?fields=id%2Cname%2CmimeType%2CisAppAuthorized%2Ccapabilities%28canCopy%2CcanAddChildren%29")


def configured_resource_id(key: str) -> str:
    resources = {**TEMPLATES, "destination": SANDBOX_FOLDER_ID}
    if key not in resources:
        raise PermissionError("SANDBOX Docs resource is not allowlisted")
    return resources[key]


def check_resource(token: str, opener, key: str) -> dict:
    """Verify one configured resource; never trust a caller-supplied file ID."""
    file_id = configured_resource_id(key)
    if not token:
        raise PermissionError("SANDBOX Google OAuth is not authorized")
    request = urllib.request.Request(metadata_url(file_id), method="GET",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Accept": "application/json"})
    with opener(request, timeout=30) as response:
        item = json.loads(response.read(64 * 1024 + 1).decode("utf-8"))
    if item.get("id") != file_id or item.get("isAppAuthorized") is not True:
        raise PermissionError(f"SANDBOX Docs {key} has no verified app authorization")
    is_folder = key == "destination"
    expected_mime = ("application/vnd.google-apps.folder" if is_folder
                     else "application/vnd.google-apps.document")
    capability = "canAddChildren" if is_folder else "canCopy"
    if item.get("mimeType") != expected_mime or item.get("capabilities", {}).get(capability) is not True:
        raise PermissionError(f"SANDBOX Docs {key} is inaccessible")
    return {"resource": key, "id": file_id, "is_app_authorized": True,
            "mime_type": expected_mime, "capability": capability}


def check_access(token: str, opener) -> dict:
    """Never copies a file; reports capability only after all exact-ID GETs."""
    if not token:
        raise PermissionError("SANDBOX Google OAuth is not authorized")
    result = {"sandbox_scopes": [DRIVE_FILE_SCOPE], "documents_created": 0,
              "destination_folder_id": SANDBOX_FOLDER_ID, "production_folder_used": False}
    for key in (*TEMPLATES, "destination"):
        check_resource(token, opener, key)
        result[key] = True
    result["ready_for_single_generation_test"] = True
    return result
