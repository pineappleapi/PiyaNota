import 'dart:math';

import '../models/auth_session.dart';
import 'auth_api.dart';
import 'auth_validators.dart';
import 'backoff.dart';

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

  /// Backend note B3.1's starting value: reset requests per email per hour,
  /// whether the email is registered or not.
  static const int resetRequestMaxPerEmail = 5;
  static const Duration resetRequestWindow = Duration(hours: 1);

  static const Duration _sessionLifetime = Duration(days: 30);
  static const String _defaultRole = 'choir_member';
  static const int _resetCodeSpace = 1000000;

  final Duration latency;
  final DateTime Function() _now;
  final Random _random;
  final Map<String, String> _passwordsByEmail = {demoEmail: demoPassword};

  /// The live reset per account: at most one, since a new request voids
  /// the old code (PIYA-303 AC5). Keyed by email because the server finds
  /// the reset by email, never by the code alone (backend note B4.2).
  final Map<String, _ResetGrant> _grantsByEmail = {};

  /// Which account each issued token belongs to, so the fake Score Library
  /// can scope its data per account the way the real API scopes by the
  /// token's `userId` (PIYA-205 AC1 / PIYA-308 AC2).
  final Map<String, String> _emailsByToken = {};

  /// Tokens minted before this fake existed came from an earlier run of
  /// the app, which this in-memory fake can't remember. They carry their
  /// account, so a stay-signed-in launch (PIYA-202-V2.2) can be demoed.
  final int _createdMicros = DateTime.now().microsecondsSinceEpoch;
  static final RegExp _tokenPattern = RegExp(r'^fake_sess_\d+_(\d+)_(.+)$');

  /// Fixed, so the demo account's own stored work survives a restart the
  /// way a real account's does (startSession compares owner ids).
  static const int demoUserId = 1;

  /// Seeded from this run's start: the device keeps an earlier run's owner
  /// id (WorkOwnerStore), so restarting at 1 let a new account inherit the
  /// demo's stored scans (PIYA-205-V2.3). One id per account, like the
  /// server, so a second login of the same account in a run keeps its work.
  // shortcut: a device clock set back between runs can repeat an earlier
  // run's id; fake builds only, upgrade if the fake ever persists accounts.
  late int _nextUserId = _createdMicros;
  final Map<String, int> _userIdsByEmail = {demoEmail: demoUserId};
  int _issuedSessions = 1;

  /// When each recent wrong current password happened, per account, for
  /// the PIYA-322 AC5 sliding window.
  final Map<String, List<DateTime>> _changePasswordFailures = {};

  /// J2 / D0.1: wrong logins per account, when the current wait ends, and
  /// which accounts sit in the long lock (the count steps back once it ends).
  static const int loginFreeFailures = 4;
  static const int loginLockAt = 10;
  static const Duration loginStep = Duration(seconds: 30);
  static const Duration loginLock = Duration(hours: 1);
  final Map<String, int> _loginFailures = {};
  final Map<String, DateTime> _loginBlockedUntil = {};
  final Set<String> _loginLocked = {};

  /// B1.4: when each account's last wrong login happened.
  final Map<String, DateTime> _lastWrongLogin = {};

  /// PIYA-204-V2.4 / B4.4: wrong reset codes per account since its last
  /// successful reset (a new code request does not clear them, B4.6), and
  /// when the current wait ends.
  final Map<String, int> _wrongCodes = {};
  final Map<String, DateTime> _wrongCodeBlockedUntil = {};

  /// B4.6: when each account's last wrong code happened.
  final Map<String, DateTime> _lastWrongCode = {};

  /// B3.1: when each recent reset request was made, per email, for the
  /// sliding hour. A request refused with 429 is not recorded.
  final Map<String, List<DateTime>> _resetRequests = {};

  /// B1.4 / B4.6: a count whose last wrong attempt is 24 h old starts over.
  static bool _isStale(DateTime? last, DateTime now) =>
      last != null && !now.isBefore(last.add(wrongCountResetAfter));

  @override
  Future<AuthSession> login({
    required String email,
    required String password,
  }) async {
    await Future<void>.delayed(latency);
    final normalized = _normalize(email);
    if (normalized.endsWith(offlineDomain)) throw const AuthNetworkException();
    final now = _now();
    final blockedUntil = _loginBlockedUntil[normalized];
    // Even the right password waits, like the real 429, so the limit can't
    // be bypassed by guessing during it.
    if (blockedUntil != null && now.isBefore(blockedUntil)) {
      throw AuthRateLimitedException(
        retryAfterSeconds: (blockedUntil.difference(now).inMilliseconds / 1000)
            .ceil(),
      );
    }
    // The idle reset comes first, then the step-down after a lock that has
    // ended (the deadline check above already passed).
    final stale = _isStale(_lastWrongLogin[normalized], now);
    if (stale) _loginLocked.remove(normalized);
    if (_loginLocked.remove(normalized)) {
      _loginFailures[normalized] = loginFreeFailures;
    }
    if (_passwordsByEmail[normalized] != password) {
      final failures = (stale ? 0 : _loginFailures[normalized] ?? 0) + 1;
      _loginFailures[normalized] = failures;
      _lastWrongLogin[normalized] = now;
      if (failures <= loginFreeFailures) {
        throw InvalidCredentialsException(
          attemptsRemaining: loginFreeFailures + 1 - failures,
        );
      }
      final wait = failures >= loginLockAt
          ? loginLock
          : loginStep * (failures - loginFreeFailures);
      if (failures >= loginLockAt) _loginLocked.add(normalized);
      _loginBlockedUntil[normalized] = now.add(wait);
      throw InvalidCredentialsException(retryAfterSeconds: wait.inSeconds);
    }
    _clearLogin(normalized);
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
    // B3.2: checked before the lookup, so a limited caller learns nothing.
    final now = _now();
    final requests = _resetRequests.putIfAbsent(normalized, () => [])
      ..removeWhere((at) => !now.isBefore(at.add(resetRequestWindow)));
    if (requests.length >= resetRequestMaxPerEmail) {
      final freesAt = requests.first.add(resetRequestWindow);
      throw AuthRateLimitedException(
        retryAfterSeconds: freesAt.difference(now).inSeconds,
      );
    }
    requests.add(now);
    if (!_passwordsByEmail.containsKey(normalized)) {
      throw const EmailNotRegisteredException();
    }

    // PIYA-303 AC5: replacing the entry voids any earlier unused code.
    _grantsByEmail[normalized] = _ResetGrant(
      code: _newCode(),
      expiresAt: now.add(resetCodeLifetime),
    );
  }

  @override
  Future<void> confirmPasswordReset({
    required String email,
    required String resetToken,
    required String newPassword,
    required String newPasswordConfirmation,
  }) async {
    await Future<void>.delayed(latency);
    final normalized = _normalize(email);
    final now = _now();
    final blockedUntil = _wrongCodeBlockedUntil[normalized];
    // B4.5: even the right code waits, so the limit can't be guessed
    // around, and a request during the wait is not counted.
    if (blockedUntil != null && now.isBefore(blockedUntil)) {
      throw AuthRateLimitedException(
        retryAfterSeconds: (blockedUntil.difference(now).inMilliseconds / 1000)
            .ceil(),
      );
    }
    final grant = _grantsByEmail[normalized];
    // B4.3: no live reset for this email (expired, used, superseded or
    // never requested) is 410, whatever the code.
    if (grant == null || !now.isBefore(grant.expiresAt)) {
      throw const ResetCodeInvalidException();
    }
    if (grant.code != resetToken.trim()) {
      // B4.4: every wrong code is a 400; from the 3rd on it also starts a
      // wait, which the next request meets as a 429.
      final stale = _isStale(_lastWrongCode[normalized], now);
      final count = (stale ? 0 : _wrongCodes[normalized] ?? 0) + 1;
      _wrongCodes[normalized] = count;
      _lastWrongCode[normalized] = now;
      if (count > resetCodeFreeAttempts) {
        _wrongCodeBlockedUntil[normalized] = now.add(
          backoffAfter(count - resetCodeFreeAttempts),
        );
      }
      throw const ResetCodeWrongException();
    }
    _checkNewPassword(newPassword, newPasswordConfirmation);
    // PIYA-304 AC4: single use — consumed only once the reset succeeds, so
    // a weak-password 400 doesn't burn the user's code.
    _grantsByEmail.remove(normalized);
    _wrongCodes.remove(normalized);
    _wrongCodeBlockedUntil.remove(normalized);
    _lastWrongCode.remove(normalized);
    _passwordsByEmail[normalized] = newPassword;
    // PIYA-202-V2.1: a reset proves control of the mailbox, so it lifts any
    // login wait the forgotten password caused.
    _clearLogin(normalized);
  }

  void _clearLogin(String normalized) {
    _loginFailures.remove(normalized);
    _loginBlockedUntil.remove(normalized);
    _lastWrongLogin.remove(normalized);
    _loginLocked.remove(normalized);
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
    final email = accountForToken(token);
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
    final grant = _grantsByEmail[_normalize(email)];
    if (grant == null || !_now().isBefore(grant.expiresAt)) return null;
    return grant.code;
  }

  /// The (normalized) email a token from this fake was issued to, or null
  /// for an unknown token — the fake equivalent of the server's 401.
  String? accountForToken(String token) =>
      _emailsByToken[token] ?? _fromEarlierRun(token);

  /// shortcut: any earlier-run token of a still-registered account (only
  /// [demoEmail] survives a restart) is honoured, so a revocation made in
  /// that run is forgotten; fine for the fake, the real server decides.
  String? _fromEarlierRun(String token) {
    final match = _tokenPattern.firstMatch(token);
    final issued = int.tryParse(match?.group(1) ?? '');
    final email = match?.group(2);
    if (issued == null || email == null || issued >= _createdMicros) {
      return null;
    }
    return _passwordsByEmail.containsKey(email) ? email : null;
  }

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

  String _newCode() =>
      _random.nextInt(_resetCodeSpace).toString().padLeft(resetCodeLength, '0');

  String _normalize(String email) => email.trim().toLowerCase();

  AuthSession _issueSession(String email) {
    final userId = _userIdsByEmail.putIfAbsent(email, () => _nextUserId++);
    // The serial, not the userId, keeps two sessions of one account apart
    // when they are issued in the same microsecond.
    final token =
        'fake_sess_${_issuedSessions++}_'
        '${DateTime.now().microsecondsSinceEpoch}_$email';
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
  const _ResetGrant({required this.code, required this.expiresAt});

  final String code;
  final DateTime expiresAt;
}
