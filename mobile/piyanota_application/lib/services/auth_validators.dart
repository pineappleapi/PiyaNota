/// Client-side mirrors of the Module 3 validation rules, so Sign-Up can
/// flag problems before a round trip (PIYA-203 AC2–4). The server stays the
/// authority — its 400 responses are still surfaced if these drift.
class AuthValidators {
  AuthValidators._();

  // Pragmatic shape check (something@something.tld), not RFC 5322 — the
  // backend is the real gate and a stricter regex only rejects valid
  // addresses.
  static final RegExp _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
  static final RegExp _letter = RegExp('[A-Za-z]');
  static final RegExp _digit = RegExp('[0-9]');

  /// PIYA-301 AC3: min. 8 characters, at least 1 letter and 1 number.
  static const int minPasswordLength = 8;
  static const String passwordPolicyDescription =
      'Use at least 8 characters, with at least one letter and one number.';

  static bool isValidEmail(String email) =>
      _emailPattern.hasMatch(email.trim());

  static bool meetsPasswordPolicy(String password) =>
      password.length >= minPasswordLength &&
      _letter.hasMatch(password) &&
      _digit.hasMatch(password);
}
