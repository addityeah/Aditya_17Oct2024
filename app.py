import csv
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import pytz
from flask import Flask, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy

# Initialize Flask and configure the database connection
app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "mysql+mysqlconnector://username:Password!123@localhost/uptime_monitoring"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# Define the models for the database
class PollData(db.Model):
    __tablename__ = "poll_data"
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.String(50), nullable=False)
    timestamp_utc = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(10), nullable=False)  # 'active' or 'inactive'


class BusinessHours(db.Model):
    __tablename__ = "business_hours"
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.String(50), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0 = Monday, 6 = Sunday
    start_time_local = db.Column(db.Time, nullable=False)
    end_time_local = db.Column(db.Time, nullable=False)


class Timezones(db.Model):
    __tablename__ = "timezones"
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.String(50), nullable=False)
    timezone_str = db.Column(db.String(50), nullable=False)


class Report(db.Model):
    __tablename__ = "reports"
    report_id = db.Column(db.String(100), primary_key=True)
    status = db.Column(db.String(20), nullable=False)  # 'Running' or 'Complete'
    csv_file = db.Column(db.String(100), nullable=True)


# Database initialization (to be run only once)
# with app.app_context():
#     print("Creating database tables...")
#     db.create_all()
#     print("Database tables created.")


# Helper function to load CSV data into the database
def load_csv_data():
    print("Loading CSV data into the database...")
    poll_data = pd.read_csv("store_status.csv")
    business_hours = pd.read_csv("Menu_hours.csv")
    timezones = pd.read_csv("bq-results-20230125-202210-1674678181880.csv")

    # Load Store status
    for _, row in poll_data.iterrows():
        poll = PollData(
            store_id=row["store_id"],
            status=row["status"],
            timestamp_utc=pd.to_datetime(row["timestamp_utc"]),
        )
        db.session.add(poll)

    print("Store status loaded.")

    # Load Business Hours
    for _, row in business_hours.iterrows():
        hours = BusinessHours(
            store_id=row["store_id"],
            day_of_week=row["day"],
            start_time_local=datetime.strptime(
                row["start_time_local"], "%H:%M:%S"
            ).time(),
            end_time_local=datetime.strptime(row["end_time_local"], "%H:%M:%S").time(),
        )
        db.session.add(hours)

    print("Business hours loaded.")

    # Load Timezones
    for _, row in timezones.iterrows():
        timezone = Timezones(store_id=row["store_id"], timezone_str=row["timezone_str"])
        db.session.add(timezone)

    print("Timezones loaded.")

    db.session.commit()
    print("CSV data loaded into the database.")


# Utility functions for time conversion
def convert_to_local_time(store_id, timestamp_utc):
    timezone = Timezones.query.filter_by(store_id=store_id).first()
    timezone_str = timezone.timezone_str if timezone else "America/Chicago"
    local_tz = pytz.timezone(timezone_str)
    utc_time = timestamp_utc.replace(tzinfo=pytz.utc)

    return utc_time.astimezone(local_tz)

def get_business_hours(store_id):
    store_hours = BusinessHours.query.filter_by(store_id=store_id).all()
    if not store_hours:
        # Assume 24/7 if business hours are missing
        return [{
            'day_of_week': i,
            'start_time_local': datetime.strptime('00:00:00', '%H:%M:%S').time(),
            'end_time_local': datetime.strptime('23:59:59', '%H:%M:%S').time()
        } for i in range(7)]  # One entry per day of the week
    return store_hours


# Function to calculate uptime/downtime based on business hours and poll data

def calculate_uptime_downtime(store_id, business_hours, polls, timezone_str):
    print(f"Calculating uptime and downtime for store {store_id}...")

    local_tz = pytz.timezone(timezone_str)
    now_utc = max([poll.timestamp_utc for poll in polls])  # Max timestamp as 'now'
    now_local = now_utc.astimezone(local_tz)

    # Time ranges for last hour, day, and week
    last_hour = now_local - timedelta(hours=1)
    last_day = now_local - timedelta(days=1)
    last_week = now_local - timedelta(weeks=1)

    # Initialize uptime and downtime counters
    uptime_last_hour = downtime_last_hour = 0
    uptime_last_day = downtime_last_day = 0
    uptime_last_week = downtime_last_week = 0

    def calculate_for_range(start, end):
        total_time = (end - start).total_seconds() / 60  # Convert to minutes
        active_time = 0

        for i in range(len(polls) - 1):
            poll_start = polls[i].timestamp_utc.astimezone(local_tz)
            poll_end = polls[i + 1].timestamp_utc.astimezone(local_tz)

            if poll_start > end or poll_end < start:
                continue

            # Clip poll times to the business hours window
            period_start = max(poll_start, start)
            period_end = min(poll_end, end)
            poll_duration = (
                period_end - period_start
            ).total_seconds() / 60  # in minutes

            if polls[i].status == "active":
                active_time += poll_duration

        inactive_time = total_time - active_time
        return active_time, inactive_time


    # Loop through business hours to calculate uptime/downtime
    for hours in business_hours:
        day_of_week = hours.day_of_week
        start_time_local = hours.start_time_local
        end_time_local = hours.end_time_local

        for i in range(7):  # Loop through the week
            business_day = now_local - timedelta(days=i)
            if business_day.weekday() == day_of_week:
                start_business_day = business_day.replace(
                    hour=start_time_local.hour, minute=start_time_local.minute
                )
                end_business_day = business_day.replace(
                    hour=end_time_local.hour, minute=end_time_local.minute
                )

                # Calculate uptime/downtime for the last hour, day, week
                if (
                    start_business_day <= last_hour <= end_business_day
                    or start_business_day <= now_local <= end_business_day
                ):
                    active, inactive = calculate_for_range(last_hour, now_local)
                    uptime_last_hour += active
                    downtime_last_hour += inactive

                if (
                    start_business_day <= last_day <= end_business_day
                    or start_business_day <= now_local <= end_business_day
                ):
                    active, inactive = calculate_for_range(last_day, now_local)
                    uptime_last_day += active / 60  # Convert to hours
                    downtime_last_day += inactive / 60  # Convert to hours

                if (
                    start_business_day <= last_week <= end_business_day
                    or start_business_day <= now_local <= end_business_day
                ):
                    active, inactive = calculate_for_range(last_week, now_local)
                    uptime_last_week += active / 60  # Convert to hours
                    downtime_last_week += inactive / 60  # Convert to hours

    return {
        "uptime_last_hour": round(uptime_last_hour, 2),
        "downtime_last_hour": round(downtime_last_hour, 2),
        "uptime_last_day": round(uptime_last_day, 2),
        "downtime_last_day": round(downtime_last_day, 2),
        "uptime_last_week": round(uptime_last_week, 2),
        "downtime_last_week": round(downtime_last_week, 2),
    }


# Route for the home
@app.route("/")
def home():
    return "Welcome to the Uptime Monitoring App"


# Route to trigger the report generation
@app.route("/trigger_report", methods=["POST"])
def trigger_report():
    report_id = str(uuid.uuid4())
    new_report = Report(report_id=report_id, status="Running")
    db.session.add(new_report)
    db.session.commit()

    # Trigger report generation in background (simplified for this example)
    print(f"Triggering report generation for report ID: {report_id}")
    generate_report(report_id)
    return jsonify({"report_id": report_id})


# Route to check the status of the report
@app.route("/get_report/<report_id>", methods=["GET"])
def get_report(report_id):
    report = Report.query.filter_by(report_id=report_id).first()

    # Check if the report exists
    if report is None:
        return jsonify({"error": "Report not found"}), 404

    if report.status == "Running":
        return jsonify({"status": "Running"})

    return send_file(report.csv_file, as_attachment=True)


# Function to generate the report
def generate_report(report_id):
    with app.app_context():
        print(f"Generating report for report ID: {report_id}")

        # Fetch all necessary data in a single query per table
        print("Fetching distinct store IDs...")
        stores = PollData.query.with_entities(PollData.store_id).distinct().all()
        print(f"Found {len(stores)} stores.")

        print("Fetching poll data...")
        poll_data = PollData.query.order_by(PollData.timestamp_utc).all()
        print(f"Fetched {len(poll_data)} poll data entries.")

        print("Fetching business hours...")
        business_hours = BusinessHours.query.all()
        print(f"Fetched {len(business_hours)} business hours entries.")

        print("Fetching timezones...")
        timezones = Timezones.query.all()
        print(f"Fetched {len(timezones)} timezones entries.")

        # Organize data into dictionaries for faster lookup
        print("Organizing data into dictionaries...")
        polls_dict = {}
        business_hours_dict = {}
        timezones_dict = {tz.store_id: tz.timezone_str for tz in timezones}

        for poll in poll_data:
            if poll.store_id not in polls_dict:
                polls_dict[poll.store_id] = []
            polls_dict[poll.store_id].append(poll)

        for bh in business_hours:
            if bh.store_id not in business_hours_dict:
                business_hours_dict[bh.store_id] = []
            business_hours_dict[bh.store_id].append(bh)

        result_rows = []

        def process_store(store_id):
            print(f"Processing store {store_id}...")
            # Get business hours and poll data for the store
            store_business_hours = business_hours_dict.get(store_id, [])
            store_polls = polls_dict.get(store_id, [])
            timezone_str = timezones_dict.get(store_id, "America/Chicago")

            # Calculate uptime and downtime
            result = calculate_uptime_downtime(
                store_id=store_id,
                business_hours=store_business_hours,
                polls=store_polls,
                timezone_str=timezone_str,
            )

            # Append the result for this store
            result_rows.append(
                [
                    store_id,
                    result["uptime_last_hour"],
                    result["downtime_last_hour"],
                    result["uptime_last_day"],
                    result["downtime_last_day"],
                    result["uptime_last_week"],
                    result["downtime_last_week"],
                ]
            )
            print(f"Finished processing store {store_id}.")

        # Use ThreadPoolExecutor to process stores in parallel
        print("Starting parallel processing of stores...")
        with ThreadPoolExecutor() as executor:
            executor.map(lambda store: process_store(store[0]), stores)

        # Write the results to a CSV file
        csv_filename = f"report_{report_id}.csv"
        print(f"Writing results to {csv_filename}...")
        with open(csv_filename, "w", newline="") as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow(
                [
                    "store_id",
                    "uptime_last_hour",
                    "downtime_last_hour",
                    "uptime_last_day",
                    "downtime_last_day",
                    "uptime_last_week",
                    "downtime_last_week",
                ]
            )
            csv_writer.writerows(result_rows)

        # Update report status
        print("Updating report status in the database...")
        report = Report.query.filter_by(report_id=report_id).first()
        report.status = "Complete"
        report.csv_file = csv_filename
        db.session.commit()
        print(f"Report generation complete for report ID: {report_id}")


# Run the application
if __name__ == "__main__":
    with app.app_context():
        print("Starting application...")

        # Load CSV data into the database (to be run only once)
        # load_csv_data()

        app.run(debug=True)
        print("Application running.")