# Samsara Driver-Vehicle Assignment Manager

This script manages Samsara driver-vehicle assignments and provides functionality to view current assignments and remotely sign out drivers.

## Features

- **View Current Assignments**: Fetch and display all current HOS driver-vehicle assignments across your fleet
- **Remote Sign-Out**: Remotely sign out all currently assigned drivers
- **Pagination Support**: Handles large fleets with automatic pagination
- **Flexible API Helper**: Reusable API request function with pagination support

## Prerequisites

- Python 3.7+
- Samsara API token with appropriate permissions
- Access to Samsara EU API endpoint

## Installation

1. Install required dependencies:
```bash
pip install -r requirements.txt
```

2. Configure your Samsara API token as a secret with key `SAMSARA_API`

## Usage

### Command Line Interface

**View current driver-vehicle assignments:**
```bash
python handler.py assignments
```

**Sign out all currently assigned drivers:**
```bash
python handler.py signout
```

### As a Samsara Function

Deploy the script as a Samsara Function and call the `manage_assignments_and_signout_handler` function. The handler will:
1. Fetch and return all current driver-vehicle assignments
2. Sign out all currently assigned drivers
3. Return results in JSON format

## API Endpoints Used

- `GET /fleet/vehicles` - Retrieve all vehicles in the fleet
- `GET /fleet/driver-vehicle-assignments` - Get current HOS assignments
- `POST /fleet/drivers/remote-sign-out` - Remotely sign out drivers

## Configuration

The script uses the Samsara EU API endpoint (`https://api.eu.samsara.com`). If you need to use a different region, modify the `base_url` variable in the functions.

## Functions

### `make_api_request()`
Generic helper function for making API calls with:
- Support for GET, POST, PATCH, PUT, DELETE methods
- Automatic pagination handling
- Error handling and logging

### `print_current_driver_vehicle_assignments()`
Iterates through all vehicles and displays current HOS driver-vehicle assignments.

### `signout_currently_assigned_drivers()`
Fetches all current assignments and remotely signs out each assigned driver.

### `manage_assignments_and_signout_handler()`
Main handler function for use as a Samsara Function that combines both operations.

## Notes

- The script filters for HOS (Hours of Service) assignments only
- Pagination is handled automatically for fleets with many vehicles
- All API responses are logged for debugging purposes
- Sign-out operations include error handling to continue processing even if individual sign-outs fail
