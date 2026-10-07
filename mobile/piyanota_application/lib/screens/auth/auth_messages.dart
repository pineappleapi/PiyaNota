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

  static const String emailRequired = 'Enter your email address';
  static const String emailInvalid = 'Enter a valid email address';
  static const String passwordsDoNotMatch = 'Passwords do not match';
  // Worded differently from the always-visible helper text
  // (AuthValidators.passwordPolicyDescription) so the error isn't just the
  // same sentence turning red.
  static const String passwordTooWeak =
      'Password is too weak — it needs 8+ characters, a letter and a number.';
}
