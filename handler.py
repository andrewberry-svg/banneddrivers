import json
import requests
import samsara


def make_api_request(api_token, method, url, params=None, headers=None, body=None):
    """
    Helper function to make REST API calls with support for different HTTP methods and pagination.
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

            if "pagination" in response_data and response_data["pagination"].get("hasNextPage", False):
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


def list_all_drivers(api_token, base_url):
    """
    Retrieve every driver in the fleet using the List Drivers endpoint.
    """
    drivers = []
    next_cursor = None

    while True:
        params = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor

        drivers_response = make_api_request(
            api_token=api_token,
            method="GET",
            url=f"{base_url}/fleet/drivers",
            params=params,
        )

        data = drivers_response.json()
        page_drivers = data.get("data") or []
        drivers.extend(page_drivers)

        if data.get("pagination", {}).get("hasNextPage"):
            next_cursor = data["pagination"]["endCursor"]
        else:
            break

    return drivers


def print_all_drivers():
    """
    Fetch and print every driver that currently exists in the fleet.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = "https://api.eu.samsara.com"

    drivers = list_all_drivers(api_token, base_url)
    print(f"Fetched {len(drivers)} drivers.")

    for driver in drivers:
        driver_id = driver.get("id", "N/A")
        driver_name = driver.get("name", "N/A")
        username = driver.get("username", "N/A")
        is_deactivated = driver.get("isDeactivated", False)
        print(
            f"Driver {driver_name} (ID: {driver_id}, Username: {username}) - "
            f"Deactivated: {is_deactivated}"
        )


def signout_all_drivers():
    """
    Fetch every driver in the fleet and remotely sign them out of the Samsara Driver App.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets["SAMSARA_API"]
    base_url = "https://api.eu.samsara.com"

    drivers = list_all_drivers(api_token, base_url)
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_token}",
    }
    signout_url = f"{base_url}/fleet/drivers/remote-sign-out"

    total_signouts = 0
    seen_driver_ids = set()

    for driver in drivers:
        driver_id = driver.get("id")
        driver_name = driver.get("name", "N/A")

        if not driver_id or driver_id in seen_driver_ids:
            continue

        payload = {"driverId": driver_id}
        print(f"Signing out driver {driver_name} (ID: {driver_id})")

        try:
            signout_response = requests.post(signout_url, json=payload, headers=headers)
            signout_response.raise_for_status()
            print(f"API response: {signout_response.text}")
            total_signouts += 1
            seen_driver_ids.add(driver_id)
        except requests.exceptions.RequestException as e:
            print(f"Error signing out driver {driver_name} (ID: {driver_id}): {e}")

    print(f"\nTotal drivers signed out: {total_signouts}")


def manage_drivers_and_signout_handler(event, context):
    import io
    import sys

    assignments_output = io.StringIO()
    sys_stdout = sys.stdout
    sys.stdout = assignments_output
    print_all_drivers()
    drivers_result = assignments_output.getvalue()
    sys.stdout = sys_stdout

    signout_output = io.StringIO()
    sys.stdout = signout_output
    signout_all_drivers()
    signout_result = signout_output.getvalue()
    sys.stdout = sys_stdout

    return {
        "statusCode": 200,
        "body": json.dumps({"drivers": drivers_result, "signout": signout_result}),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "drivers":
        print_all_drivers()
    elif len(sys.argv) > 1 and sys.argv[1] == "signout":
        signout_all_drivers()
    else:
        print("Usage:")
        print("  python handler.py drivers    # Print the current driver list")
        print("  python handler.py signout    # Sign out all drivers")
