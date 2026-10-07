# new_backend/services.py
import random
from django.core.mail import send_mail
from django.conf import settings


def send_verification_email(user):
    # Generate a 6-digit OTP
    otp = f"{random.randint(100000, 999999)}"
    user.verification_code = otp
    user.save()

    subject = "Verify your Openbox Account"
    message = f"Your verification code is: {otp}"
    email_from = settings.EMAIL_HOST_USER
    recipient_list = [user.email]
    
    send_mail(subject, message, email_from, recipient_list)