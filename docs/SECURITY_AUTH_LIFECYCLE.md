# Authentication lifecycle upgrade

## Included
- Email OTP challenge for password sign-in after an email address is present.
- OTPs are hashed in SQLite, expire, are one-time use, and allow at most five attempts.
- Password reset links are hashed in SQLite, expire after 30 minutes, and are one-time use.
- Password reset increments `session_version`, invalidating previously authenticated sessions on their next request.
- Email verification flow, account-security page, user/admin help guide.
- Institution administrator account creation collects email addresses.
- Additive database migrations preserve existing users and tables.

## Setup
1. Copy `.env.auth.example` to `.env` and set private values.
2. Configure SMTP. In development only, missing SMTP logs the code/link to the application console. Never expose that console publicly.
3. For the existing local demo administrator with no email, sign in once in development and use Account security to verify an email address. After that, sign-in requires OTP.
4. Newly created users enter the email code during their first sign-in; successful OTP verification marks the email as verified.
5. In production, configure an email address for the initial administrator securely before sign-in, set `FLASK_ENV=production`, a private `SECRET_KEY`, a strong `DEMO_ADMIN_PASSWORD`, SMTP, HTTPS, and `COOKIE_SECURE=1`.

## Security notes
- This remains a prototype, not an official APAAR/ABC/DigiLocker integration.
- The current login throttle is in-memory and does not coordinate across multiple workers. Production deployment should replace it with a shared persistent rate limiter.
- CSRF tokens are required for state-changing form requests.
- Email deliverability and HTTPS must be verified in the target environment before production use.
