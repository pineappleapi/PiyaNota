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

  /// Shown only when the server says one wrong password is left (J2).
  static const String oneTryLeft = '1 try left';

  /// PIYA-202-V2.1 AC1: m:ss, e.g. "Try again in 0:30"; h:mm:ss from one
  /// hour, so the 3600 s lock reads 1:00:00 and not 60:00.
  static String tryAgainIn(Duration wait) {
    final seconds = wait.inSeconds;
    String two(int n) => n.toString().padLeft(2, '0');
    final secs = two(seconds % 60);
    if (seconds >= Duration.secondsPerHour) {
      final mins = two(seconds % Duration.secondsPerHour ~/ 60);
      return 'Try again in ${seconds ~/ Duration.secondsPerHour}:$mins:$secs';
    }
    return 'Try again in ${seconds ~/ 60}:$secs';
  }

  /// A 429 that gave no usable wait (backend note B3.2).
  static const String tooManyAttempts = 'Too many attempts. Try again later.';

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

  /// PIYA-204-V2.1 AC1 (exact text).
  static const String resetCodeSent =
      'A reset code has been sent to this email. Please check your inbox.';

  /// PIYA-204-V2.1 AC2, split around the link so the link text is the
  /// tappable, underlined part.
  static const String emailNotRegistered =
      'Email has not yet been registered. ';
  static const String createNewAccount = 'Create a new account';
  static const String emailNotRegisteredEnd = '?';
  static const String resetCodeInvalid =
      'That code is invalid or has expired. Request a new code and try again.';

  /// PIYA-204-V2.4 AC1 (exact text). Separate from [resetCodeInvalid],
  /// which is for an expired or used code (AC3).
  static const String resetCodeWrong = 'Verification code is wrong. Try again.';
  static const String resetCodeIncomplete =
      'Enter the 6-digit code from your email';
  static const String passwordResetSuccess =
      'Your password has been reset. Log in with your new password.';
}
