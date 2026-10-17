import 'dart:math';

import '../models/auth_session.dart';
import 'auth_api.dart';
import 'auth_validators.dart';

/// In-memory stand-in for the Module 3 auth API until it's deployed, so the
/// auth screens can be demoed end to end. Behaves like the real contract
/// (PIYA-301–304) for each error path the UI must distinguish:
///
/// - [demoEmail] / [demoPassword] logs in; any other pair is a 401.
/// - Signing up with an already-registered email (incl. [demoEmail]) is a 409.
/// - Any email on the [offlineDomain] simulates no connectivity.
/// - A password reset request "emails" a 6-digit code only to registered
///   addresses, but completes identically either way (PIYA-303 AC2/AC4).
///   Since there is no real mailbox, [demoInboxCodeFor] stands in for one.
class FakeAuthApi implements AuthApi {
  FakeAuthApi({
    this.latency = defaultLatency,
    DateTime Function()? clock,
    Random? random,
  }) : _now = clock ?? DateTime.now,
       _random = random ?? Random.secure();

  static const String demoEmail = 'demo@piyanota.app';
  static const String demoPassword = 'piyanota1';
  static const String offlineDomain = '@offline.test';
  static const Duration defaultLatency = Duration(milliseconds: 800);

  /// PIYA-303 AC3 gives 30 minutes as its example expiry.
  static const Duration resetCodeLifetime = Duration(minutes: 30);
  static const int resetCodeLength = AuthValidators.resetCodeLength;

  /// PIYA-322 AC5: this many wrong current passwords within the window
  /// rate-limit Change Password (the account itself is never locked).
  static const int changePasswordMaxFailures = 5;
  static const Duration changePasswordFailureWindow = Duration(minutes: 15);

  static const Duration _sessionLifetime = Duration(days: 30);
  static const String _defaultRole = 'choir_member';
  static const int _resetCodeSpace = 1000000;

  final Duration latency;
  final DateTime Function() _now;
  final Random _random;
  final Map<String, String> _passwordsByEmail = {demoEmail: demoPassword};

  /// Outstanding codes, keyed by code because PIYA-304 identifies the
  /// account by `resetToken` alone (no email in the confirm request).
  final Map<String, _ResetGrant> _grantsByCode = {};

  /// Which account each issued token belongs to, so the fake Score Library
  /// can scope its data per account the way the real API scopes by the
  /// token's `userId` (PIYA-205 AC1 / PIYA-308 AC2).
  final Map<String, String> _emailsByToken = {};
  int _nextUserId = 1;

  /// When each recent wrong current password happened, per account, for
  /// the PIYA-322 AC5 sliding window.
  final Map<String, List<DateTime>> _changePasswordFailures = {};

  @override
  Future<AuthSession> login({
    required String email,
    required String password,
  }) async {
    await Future<void>.delayed(latency);
    final normalized = _normalize(email);
    if (normalized.endsWith(offlineDomain)) throw const AuthNetworkException();
    if (_passwordsByEmail[normalized] != password) {
      throw const InvalidCredentialsException();
    }
    return _issueSession(normalized);
  }

  @override
  Future<AuthSession> signUp({
    required String email,
    required String password,
    required String passwordConfirmation,
  }) async {
    await Future<void>.delayed(latency);
    final normalized = _normalize(email);
    if (normalized.endsWith(offlineDomain)) throw const AuthNetworkException();
    _checkNewPassword(password, passwordConfirmation);
    if (_passwordsByEmail.containsKey(normalized)) {
      throw const EmailAlreadyRegisteredException();
    }
    _passwordsByEmail[normalized] = password;
    return _issueSession(normalized);
  }

  @override
  Future<void> requestPasswordReset({required String email}) async {
    await Future<void>.delayed(latency);
    final normalized = _normalize(email);
    if (normalized.endsWith(offlineDomain)) throw const AuthNetworkException();
    if (!AuthValidators.isValidEmail(normalized)) {
      throw const AuthValidationException('Enter a valid email address');
    }
    // Unregistered: nothing is "sent", but the caller sees the same success.
    if (!_passwordsByEmail.containsKey(normalized)) return;

    // PIYA-303 AC5: a new request voids any earlier unused code.
    _grantsByCode.removeWhere((_, grant) => grant.email == normalized);
    _grantsByCode[_newCode()] = _ResetGrant(
      email: normalized,
      expiresAt: _now().add(resetCodeLifetime),
    );
  }

  @override
  Future<void> confirmPasswordReset({
    required String resetToken,
    required String newPassword,
    required String newPasswordConfirmation,
  }) async {
    await Future<void>.delayed(latency);
    final grant = _grantsByCode[resetToken.trim()];
    if (grant == null || !_now().isBefore(grant.expiresAt)) {
      throw const ResetCodeInvalidException();
    }
    _checkNewPassword(newPassword, newPasswordConfirmation);
    // PIYA-304 AC4: single use — consumed only once the reset succeeds, so
    // a weak-password 400 doesn't burn the user's code.
    _grantsByCode.remove(resetToken.trim());
    _passwordsByEmail[grant.email] = newPassword;
  }

  /// PIYA-322 stand-in, in the contract's order: session (AC1), rate limit
  /// (AC5), current password (AC3), then the Sign-Up rule (AC4). The limit
  /// is checked before the password so a limited caller can't keep
  /// guessing; once limited, even the right password waits.
  @override
  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  }) async {
    await Future<void>.delayed(latency);
    final email = _emailsByToken[token];
    if (email == null) throw const AuthSessionExpiredException();
    if (email.endsWith(offlineDomain)) throw const AuthNetworkException();

    final now = _now();
    final failures = _changePasswordFailures.putIfAbsent(email, () => [])
      ..removeWhere((at) => !now.isBefore(at.add(changePasswordFailureWindow)));
    if (failures.length >= changePasswordMaxFailures) {
      final freesAt = failures.first.add(changePasswordFailureWindow);
      throw AuthRateLimitedException(
        retryAfterSeconds: freesAt.difference(now).inSeconds,
      );
    }
    if (_passwordsByEmail[email] != currentPassword) {
      failures.add(now);
      throw const CurrentPasswordIncorrectException();
    }

    // PIYA-322 sends no confirmation field (the app checks the match), so
    // only the strength rule applies here.
    if (!AuthValidators.meetsPasswordPolicy(newPassword)) {
      throw const AuthValidationException(
        AuthValidators.passwordPolicyDescription,
        code: weakPasswordCode,
        field: newPasswordField,
      );
    }
    _passwordsByEmail[email] = newPassword;
    // AC6: every other session of the account ends; the caller's stays.
    _emailsByToken.removeWhere(
      (other, owner) => owner == email && other != token,
    );
  }

  /// The code most recently "emailed" to [email], or null if nothing was
  /// sent (unregistered address) or it expired. Debug demo aid only — the
  /// real API never returns the code to the client.
  String? demoInboxCodeFor(String email) {
    final normalized = _normalize(email);
    final now = _now();
    for (final MapEntry(key: code, value: grant) in _grantsByCode.entries) {
      if (grant.email == normalized && now.isBefore(grant.expiresAt)) {
        return code;
      }
    }
    return null;
  }

  /// The (normalized) email a token from this fake was issued to, or null
  /// for an unknown token — the fake equivalent of the server's 401.
  String? accountForToken(String token) => _emailsByToken[token];

  void _checkNewPassword(String password, String confirmation) {
    if (password != confirmation) {
      throw const AuthValidationException('Passwords do not match.');
    }
    if (!AuthValidators.meetsPasswordPolicy(password)) {
      throw const AuthValidationException(
        AuthValidators.passwordPolicyDescription,
      );
    }
  }

  String _newCode() {
    String code;
    do {
      code = _random
          .nextInt(_resetCodeSpace)
          .toString()
          .padLeft(resetCodeLength, '0');
    } while (_grantsByCode.containsKey(code));
    return code;
  }

  String _normalize(String email) => email.trim().toLowerCase();

  AuthSession _issueSession(String email) {
    final userId = _nextUserId++;
    final token =
        'fake_sess_${userId}_${DateTime.now().microsecondsSinceEpoch}';
    _emailsByToken[token] = email;
    return AuthSession(
      userId: userId,
      email: email,
      role: _defaultRole,
      sessionToken: token,
      expiresAt: DateTime.now().toUtc().add(_sessionLifetime),
    );
  }
}

class _ResetGrant {
  const _ResetGrant({required this.email, required this.expiresAt});

  final String email;
  final DateTime expiresAt;
}
