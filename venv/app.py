# app.py
# Main Flask application logic, routes, and database initialization
# --- Updated with OCR Logic for Assisted Entry ---

import os
import datetime
import calendar
import re # Import regular expression module
from dateutil.parser import parse as dateutil_parse # For flexible date parsing
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename # For secure file uploads
from dotenv import load_dotenv
from models import db, Household, Payment # Import db and models from models.py

# --- OCR Imports ---
# Ensure libraries are installed: pip install pytesseract Pillow
import pytesseract
from PIL import Image # Pillow library for image handling

# --- Configure Tesseract Path (IMPORTANT - Uncomment and adjust if needed) ---
# If Tesseract isn't in your system PATH, tell pytesseract where it is.
# Example for Windows (adjust path as necessary):
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# Example for Linux/macOS (if installed in a non-standard location):
# pytesseract.pytesseract.tesseract_cmd = r'/usr/local/bin/tesseract'


# Load environment variables from .env file
load_dotenv()

# --- Constants ---
UPLOAD_FOLDER = 'uploads' # Folder to store temporary uploads
ALLOWED_EXTENSIONS_CHAT = {'txt'}
ALLOWED_EXTENSIONS_IMG = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
LATE_PAYMENT_DAY = 21 # Day of the month after which payment is considered late

# Create and configure the Flask application instance
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-fallback-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///instance/maintenance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER # Configure upload folder

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize SQLAlchemy with the Flask app
db.init_app(app)

# --- Utility Functions [allowed_file, get_or_create_payment_record, parse_flat_wing_from_caption] ---
# (Include the definitions for these functions as provided in maintenance_tracker_app_py_v3)
def allowed_file(filename, allowed_extensions):
    """Checks if the uploaded file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

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
            status='Pending', # Default status
            is_late=False # Default late status
        )
        db.session.add(payment)
        # Commit happens in the calling function or route
    return payment

def parse_flat_wing_from_caption(caption):
    """
    Attempts to extract flat number and wing from caption text using regex.
    !! This function will likely need significant adjustment based on actual caption formats !!
    Returns: tuple (flat_number, wing) or (None, None)
    """
    flat_number = None
    wing = None
    # Handle potential None caption
    if caption is None:
        return None, None
    caption_lower = caption.lower()

    # --- Regex Patterns (Examples - Adjust based on your group's usage) ---
    # Pattern 1: "Flat A-101", "Flat: 101", "Flat No 101" (captures number/alphanumeric after "flat")
    match_flat = re.search(r'flat\s*(?:no\.?|number|[:\-])?\s*([\w\d\-]+)', caption_lower)
    # Pattern 2: "Wing C", "Wing: A" (captures single letter/word after "wing")
    match_wing = re.search(r'wing\s*[:\-]?\s*([a-zA-Z]+)', caption_lower)
     # Pattern 3: Combined like "A-101", "C 203", "D601" (assumes Wing is letter, Flat is number)
     # Updated to handle wing/flat without separator and optional leading text
    match_combined = re.search(r'(?:^|\s)([a-zA-Z])\s*[\-]?\s*(\d+)', caption) # Wing-Flat or Wing Flat
    match_combined_no_sep = re.search(r'(?:^|\s)([a-zA-Z])(\d{3})(?:\s|$)', caption) # WingFlat (e.g., D601) - assumes 3 digits for flat

    if match_flat:
        flat_number = match_flat.group(1).upper().replace('-', '') # Extract first capture group, remove hyphens
    if match_wing:
        wing = match_wing.group(1).upper() # Extract first capture group

    # If wing/flat not found individually, check combined patterns
    if not flat_number and not wing:
         if match_combined:
             wing = match_combined.group(1).upper()
             flat_number = match_combined.group(2)
         elif match_combined_no_sep:
             wing = match_combined_no_sep.group(1).upper()
             flat_number = match_combined_no_sep.group(2)


    # Basic validation/cleanup (optional)
    # if flat_number and not flat_number.isalnum(): flat_number = None # Allow digits only maybe?
    # if wing and not wing.isalpha(): wing = None # Ensure alphabetic

    # If only flat number found, try common single-letter wing pattern like "A 101" or "C-101" before number
    if flat_number and not wing:
        # Look for Wing<separator>Flat
        match_wing_first = re.search(r'([a-zA-Z])\s*[\-]?\s*' + re.escape(flat_number), caption)
        if match_wing_first:
            wing = match_wing_first.group(1).upper()

    # If only wing found, try finding number after wing "Wing A 101"
    if wing and not flat_number:
        match_flat_after = re.search(re.escape(wing) + r'\s+[\-]?\s*(\d+)', caption, re.IGNORECASE)
        if match_flat_after:
            flat_number = match_flat_after.group(1)

    # --- Add more specific patterns as needed based on your data ---
    # Example: If people write "Payment for 101 B"
    match_payment_for = re.search(r'payment\s+for\s+(\d+)\s+([a-zA-Z])', caption_lower)
    if not flat_number and match_payment_for:
        flat_number = match_payment_for.group(1)
        wing = match_payment_for.group(2).upper()

    # Example: Just "C201"
    match_simple_wing_flat = re.search(r'(?:^|\s)([a-zA-Z])(\d{3})(?:\s|$|\W)', caption) # Wing + 3 digits
    if not flat_number and not wing and match_simple_wing_flat:
         wing = match_simple_wing_flat.group(1).upper()
         flat_number = match_simple_wing_flat.group(2)


    # Return extracted values (could be None)
    return flat_number, wing


# --- Routes [/, /add_household, /edit_household, /delete_household, /record_payment, /upload_chat] ---
# (Include the definitions for these routes as provided in maintenance_tracker_app_py_v3)
@app.route('/')
def index():
    """Main dashboard page. Displays households and their payment status for the selected month."""
    try:
        today = datetime.date.today()
        current_month = request.args.get('month', default=today.month, type=int)
        current_year = request.args.get('year', default=today.year, type=int)

        households = Household.query.order_by(Household.wing, Household.flat_number).all()

        household_payments = []
        needs_commit = False
        for hh in households:
            payment = get_or_create_payment_record(hh.id, current_month, current_year)
            if payment in db.session.new: # Check if the record was newly created
                 needs_commit = True
            household_payments.append({'household': hh, 'payment': payment})

        if needs_commit:
            db.session.commit() # Commit any newly created pending payment records

        months = list(range(1, 13))
        years = list(range(today.year - 2, today.year + 2))
        month_map = {m: calendar.month_name[m] for m in months}

        return render_template(
            'index.html',
            household_payments=household_payments,
            current_month=current_month,
            current_year=current_year,
            months=months,
            years=years,
            month_map=month_map
        )
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred loading dashboard: {e}", "error")
        month_map = {m: calendar.month_name[m] for m in range(1, 13)}
        return render_template('index.html', household_payments=[], current_month=today.month, current_year=today.year, months=[], years=[], month_map=month_map)


@app.route('/add_household', methods=['GET', 'POST'])
def add_household():
    """Handles adding a new household."""
    if request.method == 'POST':
        flat_number = request.form.get('flat_number','').strip().upper()
        wing = request.form.get('wing','').strip().upper() or None # Store empty wing as None
        owner_renter_name = request.form.get('owner_renter_name','').strip()

        if not flat_number or not owner_renter_name:
            flash('Flat Number and Owner/Renter Name are required.', 'warning')
            return render_template('household_form.html', title="Add Household", form_data=request.form)

        # Check if household already exists
        existing = Household.query.filter_by(flat_number=flat_number, wing=wing).first()
        if existing:
             flash(f'Household {wing+"-" if wing else ""}{flat_number} already exists.', 'warning')
             return render_template('household_form.html', title="Add Household", form_data=request.form)

        try:
            new_household = Household(
                flat_number=flat_number,
                wing=wing,
                owner_renter_name=owner_renter_name
            )
            db.session.add(new_household)
            db.session.commit()
            flash(f'Household {wing+"-" if wing else ""}{flat_number} added successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding household: {e}', 'error')
            return render_template('household_form.html', title="Add Household", form_data=request.form)

    return render_template('household_form.html', title="Add Household")


@app.route('/edit_household/<int:id>', methods=['GET', 'POST'])
def edit_household(id):
    """Handles editing an existing household."""
    household = Household.query.get_or_404(id)

    if request.method == 'POST':
        new_flat_number = request.form.get('flat_number','').strip().upper()
        new_wing = request.form.get('wing','').strip().upper() or None
        new_owner_renter_name = request.form.get('owner_renter_name','').strip()

        if not new_flat_number or not new_owner_renter_name:
            flash('Flat Number and Owner/Renter Name are required.', 'warning')
            # Pass current (unsaved) data back to form
            household.flat_number = new_flat_number
            household.wing = new_wing
            household.owner_renter_name = new_owner_renter_name
            return render_template('household_form.html', title="Edit Household", household=household)

        # Check for conflicts
        existing = Household.query.filter(
            Household.flat_number == new_flat_number,
            Household.wing == new_wing,
            Household.id != id
        ).first()
        if existing:
            flash(f'Another household with Flat {new_wing+"-" if new_wing else ""}{new_flat_number} already exists.', 'warning')
            household.flat_number = new_flat_number
            household.wing = new_wing
            household.owner_renter_name = new_owner_renter_name
            return render_template('household_form.html', title="Edit Household", household=household)

        try:
            household.flat_number = new_flat_number
            household.wing = new_wing
            household.owner_renter_name = new_owner_renter_name
            db.session.commit()
            flash(f'Household {household.wing+"-" if household.wing else ""}{household.flat_number} updated successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating household: {e}', 'error')
            # Pass current (unsaved) data back to form
            household.flat_number = new_flat_number
            household.wing = new_wing
            household.owner_renter_name = new_owner_renter_name
            return render_template('household_form.html', title="Edit Household", household=household)

    # GET request
    return render_template('household_form.html', title="Edit Household", household=household)


@app.route('/delete_household/<int:id>', methods=['POST'])
def delete_household(id):
    """Handles deleting a household."""
    household = Household.query.get_or_404(id)
    hh_identifier = f'{household.wing+"-" if household.wing else ""}{household.flat_number}'
    try:
        db.session.delete(household)
        db.session.commit()
        flash(f'Household {hh_identifier} and associated payments deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting household: {e}', 'error')
    return redirect(url_for('index'))


@app.route('/record_payment/<int:household_id>/<int:year>/<int:month>', methods=['GET', 'POST'])
def record_payment(household_id, year, month):
    """Handles recording or updating a payment for a specific household and month."""
    household = Household.query.get_or_404(household_id)
    payment = get_or_create_payment_record(household_id, month, year)
    hh_identifier = f'{household.wing+"-" if household.wing else ""}{household.flat_number}'

    # Commit if the record was just created by get_or_create...
    if payment in db.session.new:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f"Error preparing payment record for {hh_identifier}: {e}", "error")
            return redirect(url_for('index', month=month, year=year))

    if request.method == 'POST':
        try:
            payment.amount_paid = request.form.get('amount_paid', type=float) # Returns None if empty or invalid
            payment_date_str = request.form.get('payment_date')
            payment.status = request.form.get('status', 'Pending')
            payment.receipt_id = request.form.get('receipt_id')
            payment.notes = request.form.get('notes')

            # --- Late Payment Logic ---
            payment.is_late = False # Reset late status by default
            if payment_date_str:
                try:
                    payment.payment_date = datetime.datetime.strptime(payment_date_str, '%Y-%m-%d').date()
                    # Check if payment date is after the cutoff day for the payment month/year
                    if payment.payment_date.day > LATE_PAYMENT_DAY:
                         # Ensure we're comparing against the correct month/year context
                         # (e.g., payment on March 1st for Feb bill is not late for Feb)
                         if payment.payment_date.year == year and payment.payment_date.month == month:
                              payment.is_late = True
                         # Handle cases where payment is made in a later month (could still be late for original month)
                         elif (payment.payment_date.year > year) or \
                              (payment.payment_date.year == year and payment.payment_date.month > month):
                              # Example: Payment for Jan made on Feb 22nd is considered late for Jan.
                              payment.is_late = True


                except ValueError:
                    flash('Invalid Payment Date format. Please use YYYY-MM-DD.', 'error')
                    # Don't proceed with saving if date is invalid
                    month_name = calendar.month_name[month]
                    return render_template('payment_form.html', title="Record Payment", household=household, payment=payment, year=year, month=month, month_name=month_name)
            else:
                 payment.payment_date = None # Clear date if field is empty

            db.session.commit()
            flash(f'Payment for {hh_identifier} ({year}-{month:02d}) updated.', 'success')
            return redirect(url_for('index', month=month, year=year))

        except ValueError:
             flash('Invalid Amount Paid. Please enter a number.', 'error')
             db.session.rollback()
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating payment for {hh_identifier}: {e}', 'error')

    # GET request or if POST fails validation
    month_name = calendar.month_name[month]
    # Check if OCR data was passed via query parameters (simple way for GET redirect)
    # A more robust way might use session flashing
    ocr_data_from_query = {
        'amount': request.args.get('ocr_amount'),
        'receipt_id': request.args.get('ocr_receipt_id'),
        'date': request.args.get('ocr_date')
    }

    return render_template(
        'payment_form.html',
        title="Record Payment",
        household=household,
        payment=payment,
        year=year,
        month=month,
        month_name=month_name,
        ocr_data=ocr_data_from_query # Pass potential OCR data to template
     )


@app.route('/upload_chat', methods=['GET', 'POST'])
def upload_chat():
    """Handles uploading and parsing WhatsApp chat export file."""
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'chatfile' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['chatfile']
        # If the user does not select a file, the browser submits an empty file without a filename.
        if file.filename == '':
            flash('No selected file', 'warning')
            return redirect(request.url)

        if file and allowed_file(file.filename, ALLOWED_EXTENSIONS_CHAT):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                file.save(filepath)
                # --- Start Parsing ---
                processed_count = 0
                found_receipts = []
                errors = []

                # Regex to match a typical WhatsApp line start (adjust date format if needed)
                line_start_regex = re.compile(r'^(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}(?:\s*(?:AM|PM))?)\s+-\s+([^:]+):\s+(.*)', re.IGNORECASE)
                # Variable to hold potential multi-line message content if needed
                current_message_content = ""
                current_sender = ""
                current_timestamp_str = ""

                with open(filepath, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        processed_count += 1
                        match = line_start_regex.match(line)

                        # If it's a new message line
                        if match:
                            # First, process the *previous* accumulated message (if any)
                            if current_message_content:
                                message_lower = current_message_content.lower()
                                # *** FIX: Look for <Media omitted> as well ***
                                if '<attached:' in message_lower or 'image omitted' in message_lower or '<media omitted>' in message_lower:
                                    try:
                                        msg_datetime = dateutil_parse(current_timestamp_str, dayfirst=True) # Set dayfirst based on your export format DD/MM or MM/DD
                                        msg_month = msg_datetime.month
                                        msg_year = msg_datetime.year

                                        # Extract caption (often follows the attachment indicator or is the whole message)
                                        caption = current_message_content # Assume entire message might be caption initially
                                        # Try to refine caption extraction if possible
                                        if '<attached:' in current_message_content:
                                             caption = current_message_content.split('>')[-1].strip()
                                        elif '<Media omitted>' in current_message_content:
                                             # If media omitted is followed by text, use that text
                                             potential_caption = current_message_content.split('<Media omitted>')[-1].strip()
                                             if potential_caption:
                                                 caption = potential_caption
                                             else: # If nothing follows, likely no caption
                                                  caption = ""
                                        elif 'image omitted' in current_message_content:
                                             caption = "" # Usually no caption follows this

                                        # Attempt to find household from caption
                                        flat_num, wing_char = parse_flat_wing_from_caption(caption)

                                        if flat_num:
                                            household = Household.query.filter_by(flat_number=flat_num, wing=wing_char).first()
                                            if household:
                                                payment_record = get_or_create_payment_record(household.id, msg_month, msg_year)
                                                found_receipts.append(f"Flat {wing_char+'-' if wing_char else ''}{flat_num} (Msg Date: {msg_datetime.strftime('%Y-%m-%d')})")
                                                # Optional Enhancement: Update status
                                                # if payment_record.status == 'Pending':
                                                #    payment_record.status = 'Receipt Found'
                                                #    db.session.add(payment_record)
                                            else:
                                                errors.append(f"Household not found for: Flat {flat_num}, Wing {wing_char} (Line ~{line_num})")
                                        # else: # Optional logging
                                        #    if caption: errors.append(f"Attachment found but no flat info parsed (Line ~{line_num}): {caption[:50]}...")

                                    except Exception as parse_err:
                                        errors.append(f"Error parsing message ending line {line_num-1}: {parse_err} - Content: {current_message_content[:100]}...")

                            # Now, store the details of the *new* line found
                            current_timestamp_str, current_sender, current_message_content = match.groups()

                        # If it's a continuation of the previous message
                        else:
                            # Append the line to the current message content (stripping leading/trailing whitespace)
                            current_message_content += "\n" + line.strip()

                    # --- Process the very last message in the file ---
                    if current_message_content:
                         message_lower = current_message_content.lower()
                         if '<attached:' in message_lower or 'image omitted' in message_lower or '<media omitted>' in message_lower:
                            try:
                                msg_datetime = dateutil_parse(current_timestamp_str, dayfirst=True)
                                msg_month = msg_datetime.month
                                msg_year = msg_datetime.year
                                caption = current_message_content # Refine as above...
                                if '<attached:' in current_message_content: caption = current_message_content.split('>')[-1].strip()
                                elif '<Media omitted>' in current_message_content:
                                     potential_caption = current_message_content.split('<Media omitted>')[-1].strip(); caption = potential_caption if potential_caption else ""
                                elif 'image omitted' in current_message_content: caption = ""

                                flat_num, wing_char = parse_flat_wing_from_caption(caption)
                                if flat_num:
                                    household = Household.query.filter_by(flat_number=flat_num, wing=wing_char).first()
                                    if household:
                                        payment_record = get_or_create_payment_record(household.id, msg_month, msg_year)
                                        found_receipts.append(f"Flat {wing_char+'-' if wing_char else ''}{flat_num} (Msg Date: {msg_datetime.strftime('%Y-%m-%d')})")
                                        # Optional: Update status...
                                    else: errors.append(f"Household not found for: Flat {flat_num}, Wing {wing_char} (Last Message)")
                                # else: # Optional logging
                                #    if caption: errors.append(f"Attachment found but no flat info parsed (Last Message): {caption[:50]}...")
                            except Exception as parse_err: errors.append(f"Error parsing last message: {parse_err} - Content: {current_message_content[:100]}...")

                # --- End Parsing ---
                # Commit any potential status changes (if enhancement added)
                # try:
                #    db.session.commit()
                # except Exception as commit_err:
                #    db.session.rollback()
                #    errors.append(f"Database commit error after parsing: {commit_err}")

                # Clean up uploaded file
                os.remove(filepath)

                # Report results
                flash(f"Processed {processed_count} lines from '{filename}'.", 'info')
                if found_receipts:
                    # Use set to show unique households found
                    unique_found = sorted(list(set(found_receipts)))
                    flash("Potential receipts found for: " + ", ".join(unique_found) + ". Please verify and update payment details manually.", 'success')
                else:
                     flash("No potential receipts identified based on current parsing rules and attachment indicators.", 'info')
                if errors:
                    flash("Parsing Issues Encountered (Max 5 shown): " + "; ".join(errors[:5]), 'error') # Show first few errors

                return redirect(url_for('index'))

            except Exception as e:
                flash(f"An error occurred processing file '{filename}': {e}", 'error')
                if os.path.exists(filepath):
                    os.remove(filepath) # Clean up on error
                return redirect(request.url)
        else:
            flash('Invalid file type. Please upload a .txt file.', 'error')
            return redirect(request.url)

    # GET request: show the upload form
    return render_template('chat_upload_form.html')


# --- Route for OCR Upload ---
@app.route('/upload_receipt/<int:household_id>/<int:year>/<int:month>', methods=['POST'])
def upload_receipt(household_id, year, month):
    """Handles uploading a receipt image, performs OCR, and redirects to pre-fill payment form."""
    household = Household.query.get_or_404(household_id)
    payment = get_or_create_payment_record(household_id, month, year) # Ensure payment record exists
    hh_identifier = f'{household.wing+"-" if household.wing else ""}{household.flat_number}'

    if 'receipt_image' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('record_payment', household_id=household_id, year=year, month=month))
    file = request.files['receipt_image']
    if file.filename == '':
        flash('No selected file', 'warning')
        return redirect(url_for('record_payment', household_id=household_id, year=year, month=month))

    if file and allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG):
        filename = secure_filename(f"receipt_{household_id}_{year}_{month}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        extracted_data = {} # Dictionary to hold extracted info
        try:
            file.save(filepath)

            # --- OCR Processing ---
            try:
                img = Image.open(filepath)
                # Perform OCR - use 'eng' for English language
                text = pytesseract.image_to_string(img, lang='eng')
                # print(f"--- OCR Text for {hh_identifier} ---\n{text}\n--------------------------") # Debugging

                # --- Parse OCR Text using Regex (adjust patterns as needed) ---
                # Amount (look for ₹ symbol, handle commas)
                amount_match = re.search(r'₹\s?([\d,]+\.?\d*)', text)
                if amount_match:
                    amount_str = amount_match.group(1).replace(',', '') # Remove commas
                    try:
                         extracted_data['amount'] = f"{float(amount_str):.2f}" # Format as float string
                    except ValueError:
                        extracted_data['amount'] = None # Handle conversion error
                        flash("OCR found amount pattern, but couldn't convert to number.", "warning")

                # UPI Transaction ID (look for specific keywords)
                # Make regex case-insensitive
                upi_id_match = re.search(r'UPI\s+(?:transaction|txn)\s+ID\s*[:\-]?\s*(\d+)', text, re.IGNORECASE)
                if upi_id_match:
                    extracted_data['receipt_id'] = upi_id_match.group(1)

                # Date (look for common date patterns - this is often tricky)
                # Try finding lines with month names first
                date_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\s*,?\s*\d{4}', text, re.IGNORECASE)
                if date_match:
                    date_str = date_match.group(0)
                    try:
                        # Use dateutil parser for flexibility
                        parsed_date = dateutil_parse(date_str)
                        extracted_data['date'] = parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                         extracted_data['date'] = None
                         flash("OCR found date pattern, but couldn't parse it.", "warning")

                flash(f"OCR processed image for {hh_identifier}. Please verify pre-filled details.", "info")

            except pytesseract.TesseractNotFoundError:
                 flash("OCR Error: Tesseract executable not found. Check installation and PATH configuration.", "error")
                 # Don't delete file yet if Tesseract is missing, user might retry
                 return redirect(url_for('record_payment', household_id=household_id, year=year, month=month))
            except Exception as ocr_err:
                 flash(f"OCR Error processing image for {hh_identifier}: {ocr_err}", "error")
            finally:
                 # Clean up uploaded file after processing attempt
                 if os.path.exists(filepath):
                      os.remove(filepath)

            # --- Redirect to the payment form with extracted data as query parameters ---
            # We use query parameters here for simplicity on GET redirect.
            # Flashing session data is another option.
            query_params = {k: v for k, v in extracted_data.items() if v is not None} # Only include non-None values
            return redirect(url_for('record_payment', household_id=household_id, year=year, month=month, **query_params))


        except Exception as e:
            flash(f"Error saving or processing image for {hh_identifier}: {e}", 'error')
            if os.path.exists(filepath):
                os.remove(filepath) # Clean up on error
            return redirect(url_for('record_payment', household_id=household_id, year=year, month=month))
    else:
        flash('Invalid file type. Allowed image types: png, jpg, jpeg, gif, bmp, webp', 'error')
        return redirect(url_for('record_payment', household_id=household_id, year=year, month=month))


# --- Custom CLI Commands ---
@app.cli.command("db-init")
def db_init():
    """Initializes the database and creates tables."""
    try:
        instance_path = os.path.join(app.root_path, 'instance')
        os.makedirs(instance_path, exist_ok=True)
        print("Creating database tables...")
        with app.app_context():
             # Drop existing tables (Use with caution - DEVELOPMENT ONLY)
             # db.drop_all()
             # print("Existing tables dropped.")
             db.create_all()
        print("Database tables created successfully.")
        print(f"Database file located at: {app.config['SQLALCHEMY_DATABASE_URI']}")
    except Exception as e:
        print(f"Error initializing database: {e}")


# --- Main Execution ---
if __name__ == '__main__':
    instance_path = os.path.join(app.root_path, 'instance')
    os.makedirs(instance_path, exist_ok=True)
    app.run(debug=True) # Keep debug=True for development

