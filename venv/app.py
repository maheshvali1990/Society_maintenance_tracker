# app.py
# Main Flask application logic, routes, and database initialization
# --- Updated to fix strftime TypeError ---

import os
import datetime
import calendar # Import the calendar module
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
from models import db, Household, Payment # Import db and models from models.py

# Load environment variables from .env file
load_dotenv()

# Create and configure the Flask application instance
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-fallback-secret-key') # Use env var or fallback
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///instance/maintenance.db') # Use env var or fallback
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable modification tracking

# Initialize SQLAlchemy with the Flask app
db.init_app(app)

# --- Utility Functions ---
def get_or_create_payment_record(household_id, month, year):
    """Gets an existing payment record or creates a new one if it doesn't exist."""
    payment = Payment.query.filter_by(
        household_id=household_id,
        payment_month=month,
        payment_year=year
    ).first()
    if not payment:
        payment = Payment(
            household_id=household_id,
            payment_month=month,
            payment_year=year,
            status='Pending' # Default status
            # Add expected_amount here if you have a standard monthly fee
        )
        db.session.add(payment)
        # No commit here, will be committed by the calling route
    return payment

# --- Routes ---

@app.route('/')
def index():
    """Main dashboard page. Displays households and their payment status for the selected month."""
    try:
        # Get current month and year, defaulting to today's date
        today = datetime.date.today()
        current_month = request.args.get('month', default=today.month, type=int)
        current_year = request.args.get('year', default=today.year, type=int)

        # Fetch all households, ordered
        households = Household.query.order_by(Household.wing, Household.flat_number).all()

        # Fetch or create payment records for the selected month/year for all households
        household_payments = []
        for hh in households:
            payment = get_or_create_payment_record(hh.id, current_month, current_year)
            household_payments.append({'household': hh, 'payment': payment})

        # Commit any newly created pending payment records
        db.session.commit()

        # Generate month/year options for dropdowns/selection
        months = list(range(1, 13))
        years = list(range(today.year - 2, today.year + 2)) # Example range

        # *** FIX: Create a dictionary mapping month numbers to names ***
        month_map = {m: calendar.month_name[m] for m in months}

        return render_template(
            'index.html',
            household_payments=household_payments,
            current_month=current_month,
            current_year=current_year,
            months=months,
            years=years,
            month_map=month_map # Pass the map instead of the strftime method
        )
    except Exception as e:
        db.session.rollback() # Rollback in case of error during fetch/create
        flash(f"An error occurred: {e}", "error")
        # Ensure month_map is available even in error case for template rendering
        month_map = {m: calendar.month_name[m] for m in range(1, 13)}
        return render_template('index.html', household_payments=[], current_month=today.month, current_year=today.year, months=[], years=[], month_map=month_map)


@app.route('/add_household', methods=['GET', 'POST'])
def add_household():
    """Handles adding a new household."""
    if request.method == 'POST':
        flat_number = request.form.get('flat_number')
        wing = request.form.get('wing')
        owner_renter_name = request.form.get('owner_renter_name')

        if not flat_number or not owner_renter_name:
            flash('Flat Number and Owner/Renter Name are required.', 'warning')
            return render_template('household_form.html', title="Add Household")

        # Check if flat number already exists
        existing = Household.query.filter_by(flat_number=flat_number, wing=wing).first()
        if existing:
             flash(f'Household {wing}-{flat_number} already exists.', 'warning')
             return render_template('household_form.html', title="Add Household", form_data=request.form)

        try:
            new_household = Household(
                flat_number=flat_number,
                wing=wing,
                owner_renter_name=owner_renter_name
            )
            db.session.add(new_household)
            db.session.commit()
            flash(f'Household {wing}-{flat_number} added successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding household: {e}', 'error')

    return render_template('household_form.html', title="Add Household")


@app.route('/edit_household/<int:id>', methods=['GET', 'POST'])
def edit_household(id):
    """Handles editing an existing household."""
    household = Household.query.get_or_404(id) # Get household or return 404

    if request.method == 'POST':
        new_flat_number = request.form.get('flat_number')
        new_wing = request.form.get('wing')
        new_owner_renter_name = request.form.get('owner_renter_name')

        if not new_flat_number or not new_owner_renter_name:
            flash('Flat Number and Owner/Renter Name are required.', 'warning')
            return render_template('household_form.html', title="Edit Household", household=household)

        # Check if the new flat number/wing combination conflicts with another existing record
        existing = Household.query.filter(
            Household.flat_number == new_flat_number,
            Household.wing == new_wing,
            Household.id != id # Exclude the current household being edited
        ).first()
        if existing:
            flash(f'Another household with Flat {new_wing}-{new_flat_number} already exists.', 'warning')
            # Pass current form data back to template
            household.flat_number = new_flat_number # Temporarily update for display
            household.wing = new_wing
            household.owner_renter_name = new_owner_renter_name
            return render_template('household_form.html', title="Edit Household", household=household)

        try:
            household.flat_number = new_flat_number
            household.wing = new_wing
            household.owner_renter_name = new_owner_renter_name
            db.session.commit()
            flash(f'Household {household.wing}-{household.flat_number} updated successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating household: {e}', 'error')

    # For GET request, populate form with existing data
    return render_template('household_form.html', title="Edit Household", household=household)


@app.route('/delete_household/<int:id>', methods=['POST'])
def delete_household(id):
    """Handles deleting a household."""
    household = Household.query.get_or_404(id)
    try:
        # Deleting the household will also delete associated payments due to cascade rule
        db.session.delete(household)
        db.session.commit()
        flash(f'Household {household.wing}-{household.flat_number} and associated payments deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting household: {e}', 'error')
    return redirect(url_for('index'))


@app.route('/record_payment/<int:household_id>/<int:year>/<int:month>', methods=['GET', 'POST'])
def record_payment(household_id, year, month):
    """Handles recording or updating a payment for a specific household and month."""
    household = Household.query.get_or_404(household_id)
    payment = get_or_create_payment_record(household_id, month, year)
    # Need to commit here if get_or_create added a new pending record before form submission
    if payment not in db.session.new: # Check if it was just added
         pass # Already exists or added previously
    else:
        try:
            db.session.commit() # Commit the newly created pending record
        except Exception as e:
            db.session.rollback()
            flash(f"Error preparing payment record: {e}", "error")
            return redirect(url_for('index', month=month, year=year))


    if request.method == 'POST':
        try:
            payment.amount_paid = request.form.get('amount_paid', type=float)
            payment_date_str = request.form.get('payment_date')
            payment.payment_date = datetime.datetime.strptime(payment_date_str, '%Y-%m-%d').date() if payment_date_str else None
            payment.status = request.form.get('status', 'Pending')
            payment.receipt_id = request.form.get('receipt_id')
            payment.notes = request.form.get('notes')
            # Optional: Add logic for expected_amount if needed
            # payment.expected_amount = get_expected_amount_for_month(year, month)

            db.session.commit()
            flash(f'Payment for {household.wing}-{household.flat_number} ({year}-{month:02d}) updated.', 'success')
            return redirect(url_for('index', month=month, year=year)) # Redirect back to index showing the updated month
        except ValueError:
             flash('Invalid amount entered. Please enter a number.', 'error')
             db.session.rollback()
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating payment: {e}', 'error')

    # For GET request or if POST fails validation
    # *** FIX: Get month name using calendar ***
    month_name = calendar.month_name[month]
    return render_template(
        'payment_form.html',
        title="Record Payment",
        household=household,
        payment=payment,
        year=year,
        month=month,
        month_name=month_name # Pass the correct month name
     )


# --- Custom CLI Commands ---

@app.cli.command("db-init")
def db_init():
    """Initializes the database and creates tables."""
    try:
        # Create the 'instance' folder if it doesn't exist
        instance_path = os.path.join(app.root_path, 'instance')
        os.makedirs(instance_path, exist_ok=True)
        print("Creating database tables...")
        # Create tables based on models defined in models.py
        with app.app_context(): # Need app context for db operations
             db.create_all()
        print("Database tables created successfully (if they didn't exist).")
        print(f"Database file located at: {app.config['SQLALCHEMY_DATABASE_URI']}")
    except Exception as e:
        print(f"Error initializing database: {e}")


# --- Main Execution ---

if __name__ == '__main__':
    # Ensure the instance folder exists before running
    instance_path = os.path.join(app.root_path, 'instance')
    os.makedirs(instance_path, exist_ok=True)
    # Run the Flask development server
    # Debug=True is helpful during development but should be False in production
    app.run(debug=True)

