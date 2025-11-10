import samsara
import json
import requests
import datetime
from typing import Dict, List, Optional, Set, Any

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
    # Convert method to uppercase for consistency
    method = method.upper()

    # Set default headers if none provided
    if headers is None:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_token}'
        }

    # Convert body to JSON string if it's a dictionary
    if body is not None and isinstance(body, dict):
        body = json.dumps(body)

    # Initialize combined response data
    combined_data = None

    # Make the request based on the method
    try:
        while True:
            # Make the request
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers)
            elif method == 'POST':
                response = requests.post(url, params=params, headers=headers, data=body)
            elif method == 'PATCH':
                response = requests.patch(url, params=params, headers=headers, data=body)
            elif method == 'PUT':
                response = requests.put(url, params=params, headers=headers, data=body)
            elif method == 'DELETE':
                response = requests.delete(url, params=params, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # Raise an exception for bad status codes
            response.raise_for_status()

            # Parse the response
            response_data = response.json()

            # Handle pagination
            if 'pagination' in response_data and response_data['pagination'].get('hasNextPage', False):
                # If this is the first request, initialize combined_data
                if combined_data is None:
                    combined_data = response_data
                else:
                    # Append new data to existing data
                    if 'data' in response_data and 'data' in combined_data:
                        combined_data['data'].extend(response_data['data'])

                # Update params with the endCursor for the next request
                if params is None:
                    params = {}
                params['after'] = response_data['pagination']['endCursor']
            else:
                # No more pages or no pagination, return the response
                if combined_data is not None:
                    # Return the combined response
                    response._content = json.dumps(combined_data).encode('utf-8')
                return response

    except requests.exceptions.RequestException as e:
        print(f"Error making {method} request to {url}: {str(e)}")
        raise

def _resolve_tag_id(api_token: str, base_url: str, tag_name: str) -> Optional[str]:
    """
    Look up a Samsara tag by name and return its ID.

    Args:
        api_token: API token for authentication.
        base_url: Base URL for the Samsara API.
        tag_name: Name of the tag to find.

    Returns:
        The tag ID if found, otherwise None.
    """
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
    """
    Retrieve all drivers assigned to a specific tag.

    Args:
        api_token: API token for authentication.
        base_url: Base URL for the Samsara API.
        tag_id: ID of the tag whose drivers should be fetched.

    Returns:
        Set of driver IDs associated with the tag.
    """
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
    """
    Fetch driver-vehicle assignments within a time window.

    Args:
        api_token: API token for authentication.
        base_url: Base URL for the Samsara API.
        start_time_iso: ISO8601 formatted start time.
        end_time_iso: ISO8601 formatted end time.

    Returns:
        List of assignment records.
    """
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


def detect_banned_driver_assignments(hours: int = 2) -> List[Dict[str, Any]]:
    """
    Detect assignments where banned drivers were operating vehicles within the given window.

    Args:
        hours: Interval (in hours) to look back from now for assignments.

    Returns:
        List of assignments involving banned drivers.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = secrets.get("SAMSARA_BASE_URL", "https://api.eu.samsara.com")
    banned_tag_id = secrets.get("BANNED_DRIVER_TAG_ID")
    banned_tag_name = secrets.get("BANNED_DRIVER_TAG_NAME")

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
        return []

    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(hours=hours)
    end_time_iso = end_time.isoformat().replace("+00:00", "Z")
    start_time_iso = start_time.isoformat().replace("+00:00", "Z")

    assignments = _fetch_recent_driver_vehicle_assignments(
        api_token, base_url, start_time_iso, end_time_iso
    )

    banned_assignments: List[Dict[str, Any]] = []
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

    return banned_assignments


def print_current_driver_vehicle_assignments():
    """
    For each vehicle, fetch current HOS driver-vehicle assignments and print the mapping.
    Replicates the single-vehicle query for all vehicles in the fleet.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets['SAMSARA_API']
    base_url = 'https://api.eu.samsara.com'

    # 1. Get all vehicles (handle pagination)
    vehicles = []
    next_cursor = None
    while True:
        params = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor
        vehicles_response = make_api_request(
            api_token=api_token,
            method='GET',
            url=f'{base_url}/fleet/vehicles',
            params=params
        )
        data = vehicles_response.json()
        page_vehicles = data.get('data')
        if page_vehicles:
            vehicles.extend(page_vehicles)
        if data.get('pagination', {}).get('hasNextPage'):
            next_cursor = data['pagination']['endCursor']
        else:
            break
    print(f"Fetched {len(vehicles)} vehicles.")

    # 2. For each vehicle, fetch current HOS assignments
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_token}"
    }
    url = f"{base_url}/fleet/driver-vehicle-assignments"
    total_assignments = 0
    for v in vehicles:
        vehicle_id = v.get('id')
        vehicle_name = v.get('name', 'N/A')
        if not vehicle_id:
            continue
        params = {
            "filterBy": "vehicles",
            "vehicleIds": str(vehicle_id),
            "assignmentType": "HOS"
        }
        response = requests.get(url, params=params, headers=headers)
        print(f"\nVehicle: {vehicle_name} (ID: {vehicle_id})")
        print("Raw assignments API response:", response.text)
        data = response.json()
        assignments = data.get('data') or []
        if not assignments:
            print("No current HOS driver-vehicle assignments found for this vehicle.")
        for a in assignments:
            driver = a.get('driver', {})
            print(f"Driver {driver.get('name', 'N/A')} (ID: {driver.get('id', 'N/A')}) is currently assigned to Vehicle {vehicle_name} (ID: {vehicle_id})")
            total_assignments += 1
    print(f"\nTotal current HOS assignments found: {total_assignments}")

def signout_currently_assigned_drivers():
    """
    For each vehicle, fetch current HOS driver-vehicle assignments and remotely sign out the drivers.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets['SAMSARA_API']
    base_url = 'https://api.eu.samsara.com'

    # 1. Get all vehicles (handle pagination)
    vehicles = []
    next_cursor = None
    while True:
        params = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor
        vehicles_response = make_api_request(
            api_token=api_token,
            method='GET',
            url=f'{base_url}/fleet/vehicles',
            params=params
        )
        data = vehicles_response.json()
        page_vehicles = data.get('data')
        if page_vehicles:
            vehicles.extend(page_vehicles)
        if data.get('pagination', {}).get('hasNextPage'):
            next_cursor = data['pagination']['endCursor']
        else:
            break
    print(f"Fetched {len(vehicles)} vehicles.")

    # 2. For each vehicle, fetch current HOS assignments and sign out drivers
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_token}"
    }
    url = f"{base_url}/fleet/driver-vehicle-assignments"
    signout_url = f"{base_url}/fleet/drivers/remote-sign-out"
    total_signouts = 0
    for v in vehicles:
        vehicle_id = v.get('id')
        vehicle_name = v.get('name', 'N/A')
        if not vehicle_id:
            continue
        params = {
            "filterBy": "vehicles",
            "vehicleIds": str(vehicle_id),
            "assignmentType": "HOS"
        }
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        assignments = data.get('data') or []
        for a in assignments:
            driver = a.get('driver', {})
            driver_id = driver.get('id')
            driver_name = driver.get('name', 'N/A')
            if not driver_id:
                continue
            payload = { "driverId": driver_id }
            print(f"Signing out driver {driver_name} (ID: {driver_id}) from Vehicle {vehicle_name} (ID: {vehicle_id})")
            try:
                signout_response = requests.post(
                    signout_url,
                    json=payload,
                    headers=headers
                )
                print(f"API response: {signout_response.text}")
                total_signouts += 1
            except Exception as e:
                print(f"Error signing out driver {driver_name} (ID: {driver_id}): {e}")
    print(f"\nTotal drivers signed out: {total_signouts}")

def manage_assignments_and_signout_handler(event, context):
    import io
    import sys
    import json
    # Capture print output for assignments
    assignments_output = io.StringIO()
    sys_stdout = sys.stdout
    sys.stdout = assignments_output
    print_current_driver_vehicle_assignments()
    assignments_result = assignments_output.getvalue()
    sys.stdout = sys_stdout

    # Capture print output for signout
    signout_output = io.StringIO()
    sys.stdout = signout_output
    signout_currently_assigned_drivers()
    signout_result = signout_output.getvalue()
    sys.stdout = sys_stdout

    return {
        "statusCode": 200,
        "body": json.dumps({
            "assignments": assignments_result,
            "signout": signout_result
        })
    }


def detect_banned_driver_assignments_handler(event, context):
    """
    Lambda handler wrapping detect_banned_driver_assignments.

    Args:
        event: Invocation payload; supports optional 'hours' override.
        context: Lambda context (unused).

    Returns:
        Response containing banned driver assignments within the window.
    """
    hours_override = None
    if isinstance(event, dict):
        hours_override = event.get("hours")

    if isinstance(hours_override, (int, float)) and hours_override > 0:
        lookback_hours = int(hours_override)
    else:
        lookback_hours = 2

    assignments = detect_banned_driver_assignments(hours=lookback_hours)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "hours": lookback_hours,
                "count": len(assignments),
                "assignments": assignments,
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
                print(f"Invalid hours value '{sys.argv[2]}'. Defaulting to 2 hours.")
        detect_banned_driver_assignments(hours=hours_arg)
    else:
        print("Usage:")
        print("  python handler.py assignments   # Print current driver-vehicle assignments")
        print("  python handler.py signout       # Sign out all currently assigned drivers")
        print("  python handler.py detect-banned [hours]  # Detect banned driver assignments within the past N hours")
