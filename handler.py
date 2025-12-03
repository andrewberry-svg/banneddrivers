import samsara
import json
import requests
import datetime

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

def print_all_drivers():
    """
    Fetch all drivers in the fleet and print their information.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets['SAMSARA_API']
    base_url = 'https://api.eu.samsara.com'

    # Get all drivers (handle pagination)
    drivers = []
    next_cursor = None
    while True:
        params = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor
        drivers_response = make_api_request(
            api_token=api_token,
            method='GET',
            url=f'{base_url}/fleet/drivers',
            params=params
        )
        data = drivers_response.json()
        page_drivers = data.get('data')
        if page_drivers:
            drivers.extend(page_drivers)
        if data.get('pagination', {}).get('hasNextPage'):
            next_cursor = data['pagination']['endCursor']
        else:
            break
    
    print(f"Fetched {len(drivers)} drivers.")
    print("\nAll Drivers:")
    for driver in drivers:
        driver_id = driver.get('id', 'N/A')
        driver_name = driver.get('name', 'N/A')
        print(f"  - {driver_name} (ID: {driver_id})")

def signout_all_drivers():
    """
    Fetch all drivers in the fleet and remotely sign them out of the app.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets['SAMSARA_API']
    base_url = 'https://api.eu.samsara.com'

    # Get all drivers (handle pagination)
    drivers = []
    next_cursor = None
    while True:
        params = {"limit": 512}
        if next_cursor:
            params["after"] = next_cursor
        drivers_response = make_api_request(
            api_token=api_token,
            method='GET',
            url=f'{base_url}/fleet/drivers',
            params=params
        )
        data = drivers_response.json()
        page_drivers = data.get('data')
        if page_drivers:
            drivers.extend(page_drivers)
        if data.get('pagination', {}).get('hasNextPage'):
            next_cursor = data['pagination']['endCursor']
        else:
            break
    
    print(f"Fetched {len(drivers)} drivers.")

    # Sign out each driver
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_token}"
    }
    signout_url = f"{base_url}/fleet/drivers/remote-sign-out"
    total_signouts = 0
    total_errors = 0
    
    for driver in drivers:
        driver_id = driver.get('id')
        driver_name = driver.get('name', 'N/A')
        if not driver_id:
            print(f"Skipping driver {driver_name} - no ID found")
            continue
        
        payload = {"driverId": driver_id}
        print(f"Signing out driver {driver_name} (ID: {driver_id})")
        try:
            signout_response = requests.post(
                signout_url,
                json=payload,
                headers=headers
            )
            signout_response.raise_for_status()
            print(f"  ✓ Successfully signed out {driver_name}")
            total_signouts += 1
        except requests.exceptions.HTTPError as e:
            print(f"  ✗ Error signing out driver {driver_name} (ID: {driver_id}): {e}")
            print(f"    Response: {signout_response.text}")
            total_errors += 1
        except Exception as e:
            print(f"  ✗ Error signing out driver {driver_name} (ID: {driver_id}): {e}")
            total_errors += 1
    
    print(f"\n=== Summary ===")
    print(f"Total drivers found: {len(drivers)}")
    print(f"Successfully signed out: {total_signouts}")
    print(f"Errors: {total_errors}")

def manage_drivers_and_signout_handler(event, context):
    """
    Lambda handler function that lists all drivers and signs them out.
    """
    import io
    import sys
    import json
    
    # Capture print output for listing drivers
    drivers_output = io.StringIO()
    sys_stdout = sys.stdout
    sys.stdout = drivers_output
    print_all_drivers()
    drivers_result = drivers_output.getvalue()
    sys.stdout = sys_stdout

    # Capture print output for signout
    signout_output = io.StringIO()
    sys.stdout = signout_output
    signout_all_drivers()
    signout_result = signout_output.getvalue()
    sys.stdout = sys_stdout

    return {
        "statusCode": 200,
        "body": json.dumps({
            "drivers": drivers_result,
            "signout": signout_result
        })
    }

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print_all_drivers()
    elif len(sys.argv) > 1 and sys.argv[1] == "signout":
        signout_all_drivers()
    else:
        print("Usage:")
        print("  python handler.py list      # List all drivers in the fleet")
        print("  python handler.py signout   # Sign out all drivers from the app")
