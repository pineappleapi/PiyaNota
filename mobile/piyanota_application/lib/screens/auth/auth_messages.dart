/// User-facing auth copy. Exact strings for the AC-quoted messages come
/// straight from docs/tickets/module2-mobile.md (PIYA-202 AC2/AC7, PIYA-203
/// AC5) — tests assert on these constants, so change them deliberately.
class AuthMessages {
  AuthMessages._();

  static const String incorrectCredentials = 'Incorrect email or password';
  static const String network =
      "Can't connect — check your internet connection";
  static const String emailAlreadyRegistered =
      'An account with this email already exists';

  static const String serverError =
      'Something went wrong on our side. Please try again.';
  static const String validationFallback =
      'Please check your details and try again.';
  static const String sessionSaveFailed =
      "Couldn't save your sign-in on this device. Please try again.";

  /// PIYA-202-V2.1 AC1: m:ss, e.g. "Try again in 0:30".
  static String tryAgainIn(Duration wait) {
    final seconds = wait.inSeconds;
    final rest = (seconds % 60).toString().padLeft(2, '0');
    return 'Try again in ${seconds ~/ 60}:$rest';
  }

  /// Spoken when the wait ends; there is nothing visible to prompt it.
  static const String canTryAgain = 'You can try again now';

  static const String emailRequired = 'Enter your email address';
  static const String emailInvalid = 'Enter a valid email address';
  static const String passwordsDoNotMatch = 'Passwords do not match';
  // Worded differently from the always-visible helper text
  // (AuthValidators.passwordPolicyDescription) so the error isn't just the
  // same sentence turning red.
  static const String passwordTooWeak =
      'Password is too weak — it needs 8+ characters, a letter and a number.';

  // PIYA-204. AC2/AC3 quote "...a reset link has been sent"; the flow uses
  // an emailed code instead (process step 4 allows "link/code"), so only
  // that noun differs. Shown verbatim for registered and unregistered
  // emails alike — never vary it on the request's outcome.
  static const String resetCodeSent =
      'If this email is registered, a reset code has been sent';
  static const String resetCodeInvalid =
      'That code is invalid or has expired. Request a new code and try again.';
  static const String resetCodeIncomplete =
      'Enter the 6-digit code from your email';
  static const String passwordResetSuccess =
      'Your password has been reset. Log in with your new password.';
}
