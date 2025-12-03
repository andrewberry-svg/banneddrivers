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


def list_all_drivers():
    """
    Fetch and print all drivers in the fleet using the list drivers API endpoint.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets['SAMSARA_API']
    base_url = 'https://api.eu.samsara.com'

    # Fetch all drivers using pagination
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
        page_drivers = data.get('data', [])
        if page_drivers:
            drivers.extend(page_drivers)
        
        if data.get('pagination', {}).get('hasNextPage'):
            next_cursor = data['pagination']['endCursor']
        else:
            break
    
    print(f"\nTotal drivers found: {len(drivers)}")
    for driver in drivers:
        driver_id = driver.get('id', 'N/A')
        driver_name = driver.get('name', 'N/A')
        print(f"Driver: {driver_name} (ID: {driver_id})")
    
    return drivers


def signout_all_drivers():
    """
    Fetch all drivers using the list drivers API endpoint and remotely sign them all out.
    This signs out ALL drivers in the fleet, not just those with active HOS assignments.
    """
    function = samsara.Function()
    secrets = function.secrets().load()
    api_token = secrets['SAMSARA_API']
    base_url = 'https://api.eu.samsara.com'

    # 1. Fetch all drivers using pagination
    drivers = []
    next_cursor = None
    print("Fetching all drivers from the fleet...")
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
        page_drivers = data.get('data', [])
        if page_drivers:
            drivers.extend(page_drivers)
        
        if data.get('pagination', {}).get('hasNextPage'):
            next_cursor = data['pagination']['endCursor']
        else:
            break
    
    print(f"Fetched {len(drivers)} drivers.")

    # 2. Sign out each driver
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {api_token}"
    }
    signout_url = f"{base_url}/fleet/drivers/remote-sign-out"
    
    successful_signouts = 0
    failed_signouts = 0
    
    for driver in drivers:
        driver_id = driver.get('id')
        driver_name = driver.get('name', 'N/A')
        
        if not driver_id:
            print(f"Skipping driver {driver_name} - no driver ID found")
            failed_signouts += 1
            continue
        
        payload = {"driverId": driver_id}
        print(f"Signing out driver {driver_name} (ID: {driver_id})...")
        
        try:
            signout_response = requests.post(
                signout_url,
                json=payload,
                headers=headers
            )
            
            if signout_response.status_code == 200:
                print(f"✓ Successfully signed out {driver_name}")
                successful_signouts += 1
            else:
                print(f"✗ Failed to sign out {driver_name}. Status: {signout_response.status_code}, Response: {signout_response.text}")
                failed_signouts += 1
                
        except Exception as e:
            print(f"✗ Error signing out driver {driver_name} (ID: {driver_id}): {e}")
            failed_signouts += 1
    
    print(f"\n{'='*60}")
    print(f"Sign-out Summary:")
    print(f"  Total drivers: {len(drivers)}")
    print(f"  Successful sign-outs: {successful_signouts}")
    print(f"  Failed sign-outs: {failed_signouts}")
    print(f"{'='*60}")


def signout_all_drivers_handler(event, context):
    """
    Lambda handler for signing out all drivers in the fleet.

    Args:
        event: Invocation payload (unused).
        context: Lambda context (unused).

    Returns:
        Response containing the signout results.
    """
    import io
    import sys
    
    # Capture print output
    output = io.StringIO()
    sys_stdout = sys.stdout
    sys.stdout = output
    
    try:
        signout_all_drivers()
        result = output.getvalue()
        sys.stdout = sys_stdout
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Driver sign-out completed",
                "details": result
            })
        }
    except Exception as e:
        sys.stdout = sys_stdout
        print(f"Error in signout handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "details": output.getvalue()
            })
        }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_all_drivers()
    elif len(sys.argv) > 1 and sys.argv[1] == "signout":
        signout_all_drivers()
    else:
        print("Usage:")
        print("  python handler.py list      # List all drivers in the fleet")
        print("  python handler.py signout   # Sign out all drivers in the fleet")
