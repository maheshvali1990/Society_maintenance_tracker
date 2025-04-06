# models.py
# Defines the database structure using SQLAlchemy

from flask_sqlalchemy import SQLAlchemy
import datetime

# Initialize SQLAlchemy without attaching it to a specific Flask app yet
# It will be attached in app.py
db = SQLAlchemy()

class Household(db.Model):
    """Represents a household in the society."""
    id = db.Column(db.Integer, primary_key=True)
    flat_number = db.Column(db.String(20), unique=True, nullable=False)
    wing = db.Column(db.String(10), nullable=True)
    owner_renter_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # Relationship to payments (one household has many payments)
    payments = db.relationship('Payment', backref='household', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Household {self.wing}-{self.flat_number}>'

class Payment(db.Model):
    """Represents a monthly maintenance payment record."""
    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(db.Integer, db.ForeignKey('household.id'), nullable=False)
    payment_month = db.Column(db.Integer, nullable=False) # e.g., 1 for January, 2 for February
    payment_year = db.Column(db.Integer, nullable=False) # e.g., 2025
    amount_paid = db.Column(db.Float, nullable=True) # Amount actually paid
    expected_amount = db.Column(db.Float, nullable=True) # Expected amount for the month (optional)
    payment_date = db.Column(db.Date, nullable=True) # Date the payment was made/recorded
    status = db.Column(db.String(20), nullable=False, default='Pending') # e.g., 'Pending', 'Paid', 'Partial'
    receipt_id = db.Column(db.String(100), nullable=True) # UPI transaction ID or notes
    notes = db.Column(db.Text, nullable=True) # Any additional notes
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # Ensure a household can only have one payment record per month/year
    __table_args__ = (db.UniqueConstraint('household_id', 'payment_month', 'payment_year', name='_household_month_year_uc'),)

    def __repr__(self):
        return f'<Payment HouseholdID:{self.household_id} {self.payment_year}-{self.payment_month} Status:{self.status}>'

#--------------------------------------------------------------------------