/// Session issued by the Login (PIYA-302) / Sign-Up (PIYA-301) APIs — mirrors
/// the `data` object of their shared response schema.
class AuthSession {
  const AuthSession({
    required this.userId,
    required this.email,
    required this.role,
    required this.sessionToken,
    required this.expiresAt,
  });

  final int userId;
  final String email;
  final String role;
  final String sessionToken;
  final DateTime expiresAt;

  /// Throws [FormatException] on any missing/mistyped field, so a contract
  /// drift on the backend surfaces as an explicit error rather than a null
  /// token silently written to secure storage.
  factory AuthSession.fromJson(Map<String, dynamic> json) {
    final userId = json['userId'];
    final email = json['email'];
    final role = json['role'];
    final sessionToken = json['sessionToken'];
    final expiresAt = json['expiresAt'];

    if (userId is! int ||
        email is! String ||
        role is! String ||
        sessionToken is! String ||
        sessionToken.isEmpty ||
        expiresAt is! String) {
      throw const FormatException('Malformed auth session payload');
    }

    return AuthSession(
      userId: userId,
      email: email,
      role: role,
      sessionToken: sessionToken,
      expiresAt: DateTime.parse(expiresAt),
    );
  }
}
