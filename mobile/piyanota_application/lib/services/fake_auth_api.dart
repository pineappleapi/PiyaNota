import '../models/auth_session.dart';
import 'auth_api.dart';
import 'auth_validators.dart';

/// In-memory stand-in for the Module 3 auth API until it's deployed, so the
/// Login/Sign-Up screens can be demoed end to end. Behaves like the real
/// contract (PIYA-301/302) for each error path the UI must distinguish:
///
/// - [demoEmail] / [demoPassword] logs in; any other pair is a 401.
/// - Signing up with an already-registered email (incl. [demoEmail]) is a 409.
/// - Any email on the [offlineDomain] simulates no connectivity.
class FakeAuthApi implements AuthApi {
  FakeAuthApi({this.latency = defaultLatency});

  static const String demoEmail = 'demo@piyanota.app';
  static const String demoPassword = 'piyanota1';
  static const String offlineDomain = '@offline.test';
  static const Duration defaultLatency = Duration(milliseconds: 800);
  static const Duration _sessionLifetime = Duration(days: 30);
  static const String _defaultRole = 'choir_member';

  final Duration latency;
  final Map<String, String> _passwordsByEmail = {demoEmail: demoPassword};
  int _nextUserId = 1;

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
    if (password != passwordConfirmation) {
      throw const AuthValidationException('Passwords do not match.');
    }
    if (!AuthValidators.meetsPasswordPolicy(password)) {
      throw const AuthValidationException(
        AuthValidators.passwordPolicyDescription,
      );
    }
    if (_passwordsByEmail.containsKey(normalized)) {
      throw const EmailAlreadyRegisteredException();
    }
    _passwordsByEmail[normalized] = password;
    return _issueSession(normalized);
  }

  String _normalize(String email) => email.trim().toLowerCase();

  AuthSession _issueSession(String email) {
    final userId = _nextUserId++;
    return AuthSession(
      userId: userId,
      email: email,
      role: _defaultRole,
      sessionToken: 'fake_sess_${userId}_${DateTime.now().microsecondsSinceEpoch}',
      expiresAt: DateTime.now().toUtc().add(_sessionLifetime),
    );
  }
}
