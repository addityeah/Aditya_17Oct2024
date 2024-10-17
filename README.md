# Uptime Monitoring Backend

This project is a backend API built using Flask and SQLAlchemy to monitor the uptime and downtime of various restaurants based on their business hours and polling data. The backend generates reports for restaurant owners to analyze how often their stores went inactive during business hours. The API is designed to handle dynamic data, which is periodically updated.

## Problem Statement

Restaurants are polled periodically (approximately once an hour), and their status (active/inactive) is recorded. The API needs to generate a report on the uptime and downtime during the restaurant's business hours, interpolating missing data where necessary. The data is provided in CSV files, including:

1. Poll data (store status, timestamp)
2. Business hours (store ID, day of the week, opening/closing times)
3. Time zones (store ID, time zone)

The report includes the uptime and downtime over the last hour, day, and week.

## Features

### API Endpoints

1. **`/trigger_report`** (POST):
   - Triggers the report generation for all stores.
   - Returns a `report_id`, which is used to track the report generation status.
2. **`/get_report/<report_id>`** (GET):
   - Fetches the report status. If the report is complete, it returns the CSV file containing the report.
   - If the report is still being generated, it returns a "Running" status.

### Data Sources

- **Poll Data**: Contains the store ID, UTC timestamp, and the store status (active/inactive).
- **Business Hours**: Contains the store ID, day of the week, opening and closing times in the store's local time.
- **Time Zones**: Contains the store ID and its respective time zone.

### Report Schema

The report includes:

- **Store ID**
- **Uptime and downtime** for the last hour (in minutes), last day (in hours), and last week (in hours), calculated only within business hours. The backend extrapolates missing data based on the polling frequency.

## Code Structure

### app.py

This file contains the entire logic for the backend. The following sections explain key parts of the code:

1. **Flask Setup and Models**:
   - Flask is initialized with a MySQL connection using SQLAlchemy.
   - Four models are defined: `PollData`, `BusinessHours`, `Timezones`, and `Report` to handle the polling data, business hours, time zones, and report generation, respectively.

2. **Data Loading**:
   - `load_csv_data`: This function loads the CSV data into the database tables (`PollData`, `BusinessHours`, `Timezones`). This is executed once during initialization.

3. **Uptime/Downtime Calculation**:
   - `calculate_uptime_downtime`: This function computes the uptime and downtime of a store within its business hours based on the polling data. If polling data is missing for a given time window, the function interpolates the data based on the surrounding polls.

4. **Parallel Processing**:
   - The store reports are processed in parallel using Python’s `ThreadPoolExecutor`, which speeds up the generation of reports for multiple stores.

5. **Report Generation**:
   - `generate_report`: This function collects data for all stores, processes the uptime/downtime calculation, and writes the results into a CSV file. The report generation is triggered by the `/trigger_report` endpoint.

## Key Design Choices

1. **Dynamic Data Handling**:
   - The API is designed to handle dynamic data that is updated periodically. The `/trigger_report` endpoint always generates the report based on the latest data in the database.

2. **Extrapolation Logic**:
   - If polling data is missing for certain intervals within business hours, the system interpolates uptime and downtime based on surrounding polls. This ensures accurate reports even when the polling frequency is sparse.

3. **Threaded Report Generation**:
   - The report generation is executed in parallel across multiple stores using `ThreadPoolExecutor`. This allows for faster processing of large datasets.

4. **Database Structure**:
   - The data is stored in normalized tables (`PollData`, `BusinessHours`, `Timezones`, `Reports`) to ensure efficient querying and reporting.

5. **Error Handling**:
   - Basic error handling is implemented for scenarios like missing report IDs or incomplete reports. The report generation process updates the status in the database.

## Installation

### Prerequisites

Please refer to `requirements.txt`.

### Setup

1. Clone the repository.
2. Install the required packages:

   ```bash
   pip install -r requirements.txt
   ```

3. Set up the MySQL database and update the connection string in `app.py`.
4. Initialize the database (Uncomment the relavent sections of Python code, check the comments preceding the code).
5. Load the CSV data (Uncomment the relavent sections of Python code, check the comments preceding the code).

## Running the Application

Start the application:

```bash
python3 app.py
```

To trigger the report creation, run the following command after starting the application:

```bash
curl -X POST http://127.0.0.1:5000/trigger_report
```

Once this completes, you will receive the `report-id` in your terminal. Use this to run the command

```bash
curl http://127.0.0.1:5000/get_report/<report_id>
```

This returns the status of the report or the CSV file if the report is complete.

*P.S.: The database and MySQL credentials have been hardcoded for the purposes of this assignment. Please change it as per your requirements.*
