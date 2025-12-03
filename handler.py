import json
import requests
import samsara


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

    except requests.exceptions.RequestException as exc:
        print(f"Error making {method} request to {url}: {exc}")
        raise


def fetch_all_drivers(api_token, base_url, page_limit=512):
    """
    Retrieve all drivers in the fleet using the List Drivers endpoint.

    Args:
        api_token (str): Samsara API token.
        base_url (str): Samsara API base URL.
        page_limit (int): Page size for pagination (<= 512).

    Returns:
        list[dict]: List of driver objects returned by the API.
    """
    drivers = []
    next_cursor = None

    while True:
        params = {"limit": page_limit}
        if next_cursor:
            params["after"] = next_cursor

        response = make_api_request(
            api_token=api_token,
            method="GET",
            url=f"{base_url}/fleet/drivers",
            params=params,
        )
        data = response.json()
        page_drivers = data.get("data") or []
        drivers.extend(page_drivers)

        pagination = data.get("pagination") or {}
        if pagination.get("hasNextPage"):
            next_cursor = pagination.get("endCursor")
        else:
            break

    return drivers


def print_current_driver_vehicle_assignments():
    """
    List every driver in the fleet along with their current metadata.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = "https://api.eu.samsara.com"

    drivers = fetch_all_drivers(api_token, base_url)
    print(f"Fetched {len(drivers)} drivers.")

    for driver in drivers:
        driver_name = driver.get("name", "N/A")
        driver_id = driver.get("id", "N/A")
        driver_email = driver.get("email", "N/A")
        phone = driver.get("phone", "N/A")

        assigned_vehicle = driver.get("vehicle") or driver.get("assignedVehicle") or {}
        vehicle_name = assigned_vehicle.get("name", "N/A")
        vehicle_id = assigned_vehicle.get("id", "N/A")

        print(
            f"Driver {driver_name} (ID: {driver_id}, Email: {driver_email}, Phone: {phone})"
        )
        print(f"  Assigned vehicle: {vehicle_name} (ID: {vehicle_id})")


def signout_all_drivers():
    """
    Fetch every driver using the List Drivers endpoint and remotely sign them out.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = "https://api.eu.samsara.com"

    drivers = fetch_all_drivers(api_token, base_url)
    print(f"Fetched {len(drivers)} drivers.")

    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_token}",
    }
    signout_url = f"{base_url}/fleet/drivers/remote-sign-out"

    total_signouts = 0
    for driver in drivers:
        driver_id = driver.get("id")
        driver_name = driver.get("name", "N/A")

        if not driver_id:
            print(f"Skipping driver with missing ID: {driver}")
            continue

        payload = {"driverId": driver_id}
        print(f"Signing out driver {driver_name} (ID: {driver_id})")

        try:
            response = requests.post(signout_url, json=payload, headers=headers)
            response.raise_for_status()
            print(f"API response: {response.text}")
            total_signouts += 1
        except requests.exceptions.RequestException as exc:
            print(f"Error signing out driver {driver_name} (ID: {driver_id}): {exc}")

    print(f"\nTotal drivers signed out: {total_signouts}")


def manage_assignments_and_signout_handler(event, context):
    import io
    import sys

    assignments_output = io.StringIO()
    sys_stdout = sys.stdout
    sys.stdout = assignments_output
    print_current_driver_vehicle_assignments()
    assignments_result = assignments_output.getvalue()
    sys.stdout = sys_stdout

    signout_output = io.StringIO()
    sys.stdout = signout_output
    signout_all_drivers()
    signout_result = signout_output.getvalue()
    sys.stdout = sys_stdout

    return {
        "statusCode": 200,
        "body": json.dumps(
            {"assignments": assignments_result, "signout": signout_result}
        ),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "assignments":
        print_current_driver_vehicle_assignments()
    elif len(sys.argv) > 1 and sys.argv[1] == "signout":
        signout_all_drivers()
    else:
        print("Usage:")
        print("  python handler.py assignments   # Print current drivers and metadata")
        print("  python handler.py signout       # Sign out every driver in the fleet")
