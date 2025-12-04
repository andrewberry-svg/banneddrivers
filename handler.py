import json
import datetime
import io
from typing import Dict, List, Optional, Set, Any, Tuple

import requests
import samsara
class _TeeIO:
    """Duplicate writes to multiple streams (used to log and capture simultaneously)."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            if hasattr(stream, "flush"):
                stream.flush()



def make_api_request(api_token, method, url, params=None, headers=None, body=None):
    """
    Helper function to make REST API calls with support for different HTTP methods and pagination.

    Args:
        method (str): HTTP method (GET, POST, PATCH, DELETE, etc.)
        url (str): The endpoint URL
        params (dict, optional): URL parameters/query string parameters
        headers (dict, optional): Request headers
        body (dict, optional): Request body for POST/PATCH/PUT methods

    Returns:
        requests.Response: Response object from the API call with combined data from all pages

    Raises:
        requests.exceptions.RequestException: If the API call fails
    """
    method = method.upper()

    if headers is None:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        }

    if body is not None and isinstance(body, dict):
        body = json.dumps(body)

    combined_data = None

    try:
        while True:
            if method == "GET":
                response = requests.get(url, params=params, headers=headers)
            elif method == "POST":
                response = requests.post(url, params=params, headers=headers, data=body)
            elif method == "PATCH":
                response = requests.patch(url, params=params, headers=headers, data=body)
            elif method == "PUT":
                response = requests.put(url, params=params, headers=headers, data=body)
            elif method == "DELETE":
                response = requests.delete(url, params=params, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            response_data = response.json()

            if "pagination" in response_data and response_data["pagination"].get(
                "hasNextPage", False
            ):
                if combined_data is None:
                    combined_data = response_data
                else:
                    if "data" in response_data and "data" in combined_data:
                        combined_data["data"].extend(response_data["data"])

                if params is None:
                    params = {}
                params["after"] = response_data["pagination"]["endCursor"]
            else:
                if combined_data is not None:
                    response._content = json.dumps(combined_data).encode("utf-8")
                return response

    except requests.exceptions.RequestException as e:
        print(f"Error making {method} request to {url}: {str(e)}")
        raise


def _resolve_tag_id(api_token: str, base_url: str, tag_name: str) -> Optional[str]:
    next_cursor: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor

        response = make_api_request(
            api_token=api_token,
            method="GET",
            url=f"{base_url}/fleet/tags",
            params=params,
        )
        data = response.json()
        for tag in data.get("data", []):
            if tag.get("name") == tag_name:
                return tag.get("id")

        if not data.get("pagination", {}).get("hasNextPage"):
            break
        next_cursor = data["pagination"]["endCursor"]
    return None


def _fetch_driver_ids_by_tag(
    api_token: str, base_url: str, tag_id: str
) -> Set[str]:
    driver_ids: Set[str] = set()
    next_cursor: Optional[str] = None

    while True:
        params: Dict[str, Any] = {"limit": 512, "tagIds": str(tag_id)}
        if next_cursor:
            params["after"] = next_cursor

        response = make_api_request(
            api_token=api_token,
            method="GET",
            url=f"{base_url}/fleet/drivers",
            params=params,
        )
        data = response.json()

        for driver in data.get("data", []):
            driver_id = driver.get("id")
            if driver_id:
                driver_ids.add(driver_id)

        if not data.get("pagination", {}).get("hasNextPage"):
            break
        next_cursor = data["pagination"]["endCursor"]

    return driver_ids


def _fetch_recent_driver_vehicle_assignments(
    api_token: str, base_url: str, start_time_iso: str, end_time_iso: str
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "assignmentType": "HOS",
        "startTime": start_time_iso,
        "endTime": end_time_iso,
        "limit": 512,
    }
    response = make_api_request(
        api_token=api_token,
        method="GET",
        url=f"{base_url}/fleet/driver-vehicle-assignments",
        params=params,
    )
    data = response.json()
    return data.get("data", [])


def _send_mailgun_notification(assignments: List[Dict[str, Any]], secrets: Dict[str, Any]) -> Dict[str, Any]:
    """Send a summary email via Mailgun when banned assignments are found."""

    api_key = secrets.get("MAILGUN_API_KEY")
    domain = secrets.get("MAILGUN_DOMAIN")
    recipients_raw = secrets.get("MAILGUN_RECIPIENTS")

    status: Dict[str, Any] = {
        "sent": False,
        "recipients": [],
        "reason": None,
    }

    if not api_key or not domain or not recipients_raw:
        reason = "missing Mailgun configuration values"
        print(f"Mailgun not fully configured; skipping notification email ({reason}).")
        status["reason"] = reason
        return status

    if isinstance(recipients_raw, str):
        recipients = [addr.strip() for addr in recipients_raw.split(",") if addr.strip()]
    elif isinstance(recipients_raw, list):
        recipients = [str(addr).strip() for addr in recipients_raw if str(addr).strip()]
    else:
        recipients = []

    if not recipients:
        reason = "no valid Mailgun recipients configured"
        print("No valid Mailgun recipients configured; skipping notification email.")
        status["reason"] = reason
        return status

    from_email = secrets.get("MAILGUN_FROM_EMAIL") or f"alerts@{domain}"
    subject = secrets.get("MAILGUN_SUBJECT") or "Banned driver assignments detected"

    lines = [
        "The following banned driver assignments were detected:",
        "",
    ]
    for assignment in assignments:
        driver = assignment.get("driver") or {}
        vehicle = assignment.get("vehicle") or {}
        start = assignment.get("startTime", "Unknown start")
        end = assignment.get("endTime", "Unknown end")
        lines.append(
            f"- Driver {driver.get('name', 'N/A')} (ID: {driver.get('id', 'N/A')}) "
            f"assigned to Vehicle {vehicle.get('name', 'N/A')} (ID: {vehicle.get('id', 'N/A')}) "
            f"from {start} to {end}"
        )

    body_text = "\n".join(lines)

    try:
        response = requests.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", api_key),
            data={
                "from": from_email,
                "to": recipients,
                "subject": subject,
                "text": body_text,
            },
        )
        response.raise_for_status()
        print(f"Mailgun notification sent to {', '.join(recipients)}")
        status["sent"] = True
        status["recipients"] = recipients
        status["reason"] = "email sent successfully"
    except requests.RequestException as exc:
        reason = f"Mailgun request failed: {exc}"
        print(f"Failed to send Mailgun notification: {exc}")
        status["reason"] = reason

    return status


def detect_banned_driver_assignments(hours: int = 2) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Detect assignments where banned drivers were operating vehicles within the given window.

    Returns:
        Tuple of (assignments list, email status dict summarizing Mailgun delivery attempt).
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = secrets.get("SAMSARA_BASE_URL", "https://api.eu.samsara.com")
    banned_tag_id = secrets.get("BANNED_DRIVER_TAG_ID")
    banned_tag_name = secrets.get("BANNED_DRIVER_TAG_NAME")
    email_status: Dict[str, Any] = {
        "sent": False,
        "recipients": [],
        "reason": "email not attempted",
    }

    if not banned_tag_id:
        if not banned_tag_name:
            raise ValueError(
                "Either BANNED_DRIVER_TAG_ID or BANNED_DRIVER_TAG_NAME must be provided in secrets."
            )
        banned_tag_id = _resolve_tag_id(api_token, base_url, banned_tag_name)
        if not banned_tag_id:
            raise ValueError(
                f"Could not resolve tag ID for banned drivers tag named '{banned_tag_name}'."
            )

    banned_driver_ids = _fetch_driver_ids_by_tag(api_token, base_url, str(banned_tag_id))
    if not banned_driver_ids:
        print("No drivers found for the banned drivers tag.")
        email_status["reason"] = "no drivers found for banned tag"
        return [], email_status

    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(hours=hours)
    end_time_iso = end_time.isoformat().replace("+00:00", "Z")
    start_time_iso = start_time.isoformat().replace("+00:00", "Z")

    assignments = _fetch_recent_driver_vehicle_assignments(
        api_token, base_url, start_time_iso, end_time_iso
    )

    banned_assignments: List[Dict[str, Any]] = []
    email_status["reason"] = "no banned assignments detected"
    for assignment in assignments:
        driver = assignment.get("driver") or {}
        driver_id = driver.get("id")
        if driver_id and driver_id in banned_driver_ids:
            banned_assignments.append(assignment)

    print(
        f"Found {len(banned_assignments)} assignments with banned drivers in the last {hours} hours."
    )
    for assignment in banned_assignments:
        driver = assignment.get("driver", {})
        vehicle = assignment.get("vehicle", {})
        print(
            f"Driver {driver.get('name', 'N/A')} (ID: {driver.get('id', 'N/A')}) "
            f"was assigned to Vehicle {vehicle.get('name', 'N/A')} "
            f"(ID: {vehicle.get('id', 'N/A')})"
        )

    if banned_assignments:
        email_status = _send_mailgun_notification(banned_assignments, secrets)

    return banned_assignments, email_status


def print_current_driver_vehicle_assignments():
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = "https://api.eu.samsara.com"

    vehicles = []
    next_cursor = None
    while True:
        params = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor
        vehicles_response = make_api_request(
            api_token=api_token,
            method="GET",
            url=f"{base_url}/fleet/vehicles",
            params=params,
        )
        data = vehicles_response.json()
        page_vehicles = data.get("data")
        if page_vehicles:
            vehicles.extend(page_vehicles)
        if data.get("pagination", {}).get("hasNextPage"):
            next_cursor = data["pagination"]["endCursor"]
        else:
            break
    print(f"Fetched {len(vehicles)} vehicles.")

    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_token}",
    }
    url = f"{base_url}/fleet/driver-vehicle-assignments"
    total_assignments = 0
    for v in vehicles:
        vehicle_id = v.get("id")
        vehicle_name = v.get("name", "N/A")
        if not vehicle_id:
            continue
        params = {
            "filterBy": "vehicles",
            "vehicleIds": str(vehicle_id),
            "assignmentType": "HOS",
        }
        response = requests.get(url, params=params, headers=headers)
        print(f"\nVehicle: {vehicle_name} (ID: {vehicle_id})")
        print("Raw assignments API response:", response.text)
        data = response.json()
        assignments = data.get("data") or []
        if not assignments:
            print("No current HOS driver-vehicle assignments found for this vehicle.")
        for a in assignments:
            driver = a.get("driver", {})
            print(
                f"Driver {driver.get('name', 'N/A')} (ID: {driver.get('id', 'N/A')}) is currently assigned to Vehicle {vehicle_name} (ID: {vehicle_id})"
            )
            total_assignments += 1
    print(f"\nTotal current HOS assignments found: {total_assignments}")


def signout_currently_assigned_drivers():
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = "https://api.eu.samsara.com"

    vehicles = []
    next_cursor = None
    while True:
        params = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor
        vehicles_response = make_api_request(
            api_token=api_token,
            method="GET",
            url=f"{base_url}/fleet/vehicles",
            params=params,
        )
        data = vehicles_response.json()
        page_vehicles = data.get("data")
        if page_vehicles:
            vehicles.extend(page_vehicles)
        if data.get("pagination", {}).get("hasNextPage"):
            next_cursor = data["pagination"]["endCursor"]
        else:
            break
    print(f"Fetched {len(vehicles)} vehicles.")

    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_token}",
    }
    url = f"{base_url}/fleet/driver-vehicle-assignments"
    signout_url = f"{base_url}/fleet/drivers/remote-sign-out"
    total_signouts = 0
    for v in vehicles:
        vehicle_id = v.get("id")
        vehicle_name = v.get("name", "N/A")
        if not vehicle_id:
            continue
        params = {
            "filterBy": "vehicles",
            "vehicleIds": str(vehicle_id),
            "assignmentType": "HOS",
        }
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        assignments = data.get("data") or []
        for a in assignments:
            driver = a.get("driver", {})
            driver_id = driver.get("id")
            driver_name = driver.get("name", "N/A")
            if not driver_id:
                continue
            payload = {"driverId": driver_id}
            print(
                f"Signing out driver {driver_name} (ID: {driver_id}) from Vehicle {vehicle_name} (ID: {vehicle_id})"
            )
            try:
                signout_response = requests.post(
                    signout_url,
                    json=payload,
                    headers=headers,
                )
                print(f"API response: {signout_response.text}")
                total_signouts += 1
            except Exception as e:
                print(
                    f"Error signing out driver {driver_name} (ID: {driver_id}): {e}"
                )
    print(f"\nTotal drivers signed out: {total_signouts}")


def manage_assignments_and_signout_handler(event, context):
    import sys

    sys_stdout = sys.stdout

    assignments_output = io.StringIO()
    sys.stdout = _TeeIO(sys_stdout, assignments_output)
    try:
        print_current_driver_vehicle_assignments()
    finally:
        sys.stdout = sys_stdout
    assignments_result = assignments_output.getvalue()

    signout_output = io.StringIO()
    sys.stdout = _TeeIO(sys_stdout, signout_output)
    try:
        signout_currently_assigned_drivers()
    finally:
        sys.stdout = sys_stdout
    signout_result = signout_output.getvalue()

    banned_output = io.StringIO()
    sys.stdout = _TeeIO(sys_stdout, banned_output)
    banned_assignments: List[Dict[str, Any]] = []
    email_status: Dict[str, Any] = {
        "sent": False,
        "recipients": [],
        "reason": "banned driver detection not attempted",
    }
    try:
        banned_assignments, email_status = detect_banned_driver_assignments()
    except requests.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", "unknown")
        response_text = getattr(exc.response, "text", "no response body")
        print(
            "detect_banned_driver_assignments failed "
            f"(status={status_code}): {response_text}"
        )
        email_status = {
            "sent": False,
            "recipients": [],
            "reason": f"failed with HTTP {status_code}",
        }
    except Exception as exc:  # Catch-all to keep handler healthy
        print(f"detect_banned_driver_assignments encountered an error: {exc}")
        email_status = {
            "sent": False,
            "recipients": [],
            "reason": f"unexpected error: {exc}",
        }
    finally:
        sys.stdout = sys_stdout
    banned_result = banned_output.getvalue()

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "assignments": assignments_result,
                "signout": signout_result,
                "bannedAssignments": banned_assignments,
                "bannedAssignmentsLog": banned_result,
                "emailStatus": email_status,
            }
        ),
    }


def detect_banned_driver_assignments_handler(event, context):
    hours_override = None
    if isinstance(event, dict):
        hours_override = event.get("hours")

    if isinstance(hours_override, (int, float)) and hours_override > 0:
        lookback_hours = int(hours_override)
    else:
        lookback_hours = 2

    assignments, email_status = detect_banned_driver_assignments(hours=lookback_hours)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "hours": lookback_hours,
                "count": len(assignments),
                "assignments": assignments,
                "emailStatus": email_status,
            }
        ),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "assignments":
        print_current_driver_vehicle_assignments()
    elif len(sys.argv) > 1 and sys.argv[1] == "signout":
        signout_currently_assigned_drivers()
    elif len(sys.argv) > 1 and sys.argv[1] == "detect-banned":
        hours_arg = 2
        if len(sys.argv) > 2:
            try:
                hours_arg = int(sys.argv[2])
            except ValueError:
                print(
                    f"Invalid hours value '{sys.argv[2]}'. Defaulting to 2 hours."
                )
        assignments, email_status = detect_banned_driver_assignments(hours=hours_arg)
        print(
            f"Email notification sent: {email_status.get('sent')} | "
            f"recipients: {', '.join(email_status.get('recipients', [])) or 'N/A'} | "
            f"reason: {email_status.get('reason')}"
        )
    else:
        print("Usage:")
        print("  python handler.py assignments   # Print current driver-vehicle assignments")
        print("  python handler.py signout       # Sign out all currently assigned drivers")
        print(
            "  python handler.py detect-banned [hours]  # Detect banned driver assignments within the past N hours"
        )
